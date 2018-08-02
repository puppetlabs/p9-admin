from __future__ import print_function
import configparser
import json
import keystoneauth1
import logging
import operator
import os
import pprint
import requests
import sys

def ensure_project(client, name, assume_complete=True):
    """
    Ensure that a project and the standard resources exist

    By default (assume_complete=True) this does not check that the standard
    project resources, e.g. network1, exist if the project already exists.

    Set assume_complete=False to ensure all of the standard project resources
    exist even if the project itself already exists.
    """
    # Default set up for projects
    NETWORK_NAME = "network1"
    SUBNET_NAME = "subnet0"
    SUBNET_CIDR="192.168.0.0/24"
    ROUTER_NAME = "router0"
    SECURITY_GROUP_NAME = "default"
    DOMAIN = "default"

    # Create project
    try:
        project = client.keystone().projects.find(name=name)
        client.logger.info('Found project "%s" [%s]', project.name, project.id)
        new_project = False
        if assume_complete:
            return project
    except keystoneauth1.exceptions.NotFound:
        project = client.keystone().projects.create(name=name, domain=DOMAIN)
        client.logger.info('Created project "%s" [%s]', project.name, project.id)
        new_project = True

    # Create default network
    network = None
    if not new_project:
        network = client.find_network(project, NETWORK_NAME)
        new_network = False
    if not network:
        network = client.create_network(project, NETWORK_NAME)
        new_network = True

    # Create default subnet
    subnet = None
    if not new_network:
        subnet = client.find_subnet(project, network, SUBNET_NAME)
        new_subnet = False
    if not subnet:
        subnet = client.create_subnet(project, network, SUBNET_NAME, SUBNET_CIDR)
        new_subnet = True

    # Create default router to connect default subnet to external network
    ### FIXME should this add the router to the external network? what if
    ### it's already connected to a network? should this check all routers?
    ### if router.external_gateway_info or router.external_gateway_info["network_id"]
    router = None
    if not new_project:
        router = client.find_router(project, ROUTER_NAME)
    if not router:
        router = client.create_router(project, network, subnet, ROUTER_NAME)
        new_router = True

    ### FIXME it seems to create the default security group automatically.
    sg = client.find_security_group(project, SECURITY_GROUP_NAME)
    if not sg:
        sg = client.create_security_group(project, SECURITY_GROUP_NAME)

    # Update default security group to allow external access
    ### Should we always correct the rules?
    sg_rule = None
    if not new_project:
        sg_rule = client.find_security_group_rule(sg)
    if not sg_rule:
        sg_rule = client.create_security_group_rule(sg)

    return project


def get_quota(client, project_name):
    nova_url = "{}/os-quota-sets/{}".format(os.environ.get("OS_NOVA_URL"), project_name)

    header = {'X-AUTH-TOKEN': client.api_token(), 'Content-Type': 'application/json'}

    r = requests.get(nova_url, headers=header, verify=True)

    return r.text


def apply_quota(client, project_id, quota_name, quota_value):
    """
    Apply a quota to an existing project
    """

    nova_url = "{}/os-quota-sets/{}".format(os.environ.get("OS_NOVA_URL"), project_id)

    client.logger.info("About to set quota {} to {} on url {}".format(quota_name, quota_value, nova_url))

    header = {'X-AUTH-TOKEN': client.api_token(), 'Content-Type': 'application/json'}
    request_body = {"quota_set": {quota_name: quota_value}}
    data_json = json.dumps(request_body, sort_keys=True, indent=4, separators=(',', ': '))

    r = requests.put(nova_url, headers=header, data=data_json, verify=True)

    return r.text


def apply_quota_defaults(client, project_id):
    """
    Apply a quota to an existing project
    """
    config = configparser.ConfigParser()
    config.read('conf/defaults.ini')

    for key in config["DEFAULT"]:
        print("Applying key {} with value {}".format(key, config["DEFAULT"][key]))
        retval = apply_quota(client, project_id, key, config["DEFAULT"][key]) + "\n"

    return retval


def delete_project(client, name):
    ### FIXME: images?
    project = client.find_project(name)
    client.logger.info('Started deleting project "%s" [%s]', project.name, project.id)

    for server in client.servers(project_id=project.id):
        client.openstack().compute.delete_server(server, force=True, ignore_missing=True)
        client.logger.info('  Deleted server "%s" [%s]', server.name, server.id)

    for volume in client.volumes(project_id=project.id):
        client.openstack().block_storage.delete_volume(volume, ignore_missing=True)
        client.logger.info('  Deleted volume "%s" [%s]', volume.name, volume.id)

    network_client = client.openstack().network
    routers = network_client.routers(project_id=project.id)
    for router in routers:
        client.logger.info('  Started deleting router "%s" [%s]', router.name, router.id)
        for port in network_client.ports(device_id=router.id):
            network_client.remove_interface_from_router(router, port_id=port.id)
            client.logger.info("    Removed port %s [%s]", port.device_owner, port.id)
        network_client.delete_router(router, ignore_missing=True)
        client.logger.info('    Finished deleting router')

    networks = network_client.networks(project_id=project.id)
    for network in networks:
        client.logger.info('  Started deleting network "%s" [%s]', network.name, network.id)
        subnets = client.subnets(project_id=project.id, network_id=network.id)
        for subnet in subnets:
            network_client.delete_subnet(subnet, ignore_missing=True)
            client.logger.info('    Deleted subnet "%s" [%s]', subnet.name, subnet.id)
        network_client.delete_network(network, ignore_missing=True)
        client.logger.info('    Finished deleting network')

    # The default security group is recreating when it's deleted, so we have
    # to delete the project first.
    security_groups = list(client.security_groups(project_id=project.id))

    client.keystone().projects.delete(project)
    client.logger.info('  Deleted project itself')

    for sg in security_groups:
        network_client.delete_security_group(sg, ignore_missing=True)
        client.logger.info('  Deleted security group "%s" [%s]', sg.name, sg.id)

    client.logger.info('  Finished deleting project')


def show_project(client, name):
    ### FIXME: images?
    project = client.find_project(name)
    print('Project "{}" [{}]'.format(project.name, project.id))

    network_client = client.openstack().network
    networks = network_client.networks(project_id=project.id)
    for network in networks:
        print('  Network "{}" [{}]'.format(network.name, network.id))
        subnets = client.subnets(project_id=project.id, network_id=network.id)
        for subnet in subnets:
            print('    Subnet "{}" [{}] {}'.format(subnet.name, subnet.id, subnet.cidr))

    routers = network_client.routers(project_id=project.id)
    for router in routers:
        print('  Router "{}" [{}]'.format(router.name, router.id))
        for port in network_client.ports(device_id=router.id):
            print("    Port {} [{}]".format(port.device_owner, port.id))
            print_fixed_ips(client, port.fixed_ips)

    for sg in client.security_groups(project_id=project.id):
        print('  Security group "{}" [{}]'.format(sg.name, sg.id))

        sort_key_func = operator.attrgetter(
            "direction", "ether_type", "protocol", "remote_group_id",
            "remote_ip_prefix", "port_range_min", "port_range_max")

        sg_rules = network_client.security_group_rules(security_group_id=sg.id)
        for sg_rule in sorted(sg_rules, key=sort_key_func):
            print_security_group_rule(client, sg_rule)

    for volume in client.volumes(project_id=project.id):
        print('  Volume "{}" [{}] {} GB, {}'.format(
            volume.name, volume.id, volume.size, volume.status))

    for server in client.servers(project_id=project.id):
        print('  Server "{}" [{}] {}'.format(
            server.name, server.id, server.status))


def print_fixed_ips(client, fixed_ips):
    for ip in fixed_ips:
        subnet = client.subnet(ip["subnet_id"])
        print("      {} ({})".format(ip["ip_address"], subnet.name))

def print_security_group_rule(client, rule):
    if rule.direction == "egress":
        direction = "to"
    elif rule.direction == "ingress":
        direction = "from"
    else:
        direction = rule.direction

    if rule.remote_group_id:
        remote = "<{}>".format(client.security_group(rule.remote_group_id).name)
    elif rule.remote_ip_prefix:
        remote = rule.remote_ip_prefix
    else:
        remote = "everywhere"

    if rule.protocol == None:
        protocol = "all"
    else:
        protocol = rule.protocol

    if rule.port_range_min == None:
        port_range = "all ports"
    elif rule.port_range_min == rule.port_range_max:
        port_range = "port {}".format(rule.port_range_min)
    else:
        port_range = "ports {}-{}".format(rule.port_range_min, rule.port_range_max)

    print("    {} {} {} {} on {}".format(
        rule.ether_type, protocol, direction, remote,
        port_range))


def verified_apply_quota_defaults(client, project):
    """ Apply defaults quotas, verifying that the quota won't be lowered first """
    config = configparser.ConfigParser()
    config.read('conf/defaults.ini')

    for key in config["DEFAULT"]:
        client.logger.info("Applying key {} with value {} to project {}".format(key, config["DEFAULT"][key], project.name.encode('utf-8')))
        verified_apply_quota(client, project, key, config["DEFAULT"][key])


def verified_apply_quota(client, project, quota_name, quota_value, force=False):
    quota = get_quota(client, project.id)
    if int(quota_value) == int(json.loads(quota)["quota_set"][quota_name]):
        client.logger.info("Quota already set for project {}".format(project.name.encode('utf-8')))
        return

    if int(json.loads(quota)["quota_set"][quota_name]) == -1:
        client.logger.info("Quota for project {} set to unlimited, use apply-quota to lower")
        return

    if int(quota_value) > int(json.loads(quota)["quota_set"][quota_name]):
        client.logger.info("Increasing quota {} from {} to {} on project {}".format(quota_name, json.loads(quota)["quota_set"][quota_name], quota_value, project.name.encode('utf-8')))
        apply_quota(client, project.id, quota_name, quota_value)
    else:
        client.logger.info("Application quota larger than new quota, use apply-quota to set lower.")
