from __future__ import print_function
import click
import json
import os
import p9admin
import p9admin.validators as validators
import pprint
import sys
from time import sleep

@click.group()
def project():
    """Manage projects"""
    pass


@project.command()
@click.argument("name")
def ensure(name):
    """Ensure a project exists"""
    client = p9admin.OpenStackClient()
    project = p9admin.project.ensure_project(client, name)
    print('Project "{}" [{}]'.format(project.name, project.id))


@project.command()
@click.argument("name")
def show(name):
    """Show a project and the objects within"""
    p9admin.project.show_project(p9admin.OpenStackClient(), name)


@project.command("apply-quota-all")
@click.option("--quota-name", "-n")
@click.option("--quota-value", "-v")
@click.option("--force", "-f")
def apply_quota_all(quota_name, quota_value, force=False):
    """

    Apply a quota to all projects in the environment.
    This will not lower quotas, only raise them.  Use --force to force all quotas to the new setting, even if that would mean lowering a quota.

    quota_name is one of:

    instances
    ram
    cores
    fixed_ips
    floating_ips
    injected_file_content_bytes
    injected_file_path_bytes
    injected_files
    key_pairs
    metadata_items
    security_groups
    security_group_rules
    server_groups
    server_group_members
    networks
    subnets
    routers
    root_gb

    quota_value is a number, -1 for unlimited

    """
    client = p9admin.OpenStackClient()

    if "OS_NOVA_URL" not in os.environ:
        sys.exit("OS_NOVA_URL environment variable must be set.  Check README.rst")

    validators.quota_name(quota_name)
    validators.quota_value(quota_name, quota_value)

    projects = client.projects()

    for project in projects:

        quota = p9admin.project.get_quota(client, project.id)

        if int(quota_value) == int(json.loads(quota)["quota_set"][quota_name]):
            print("Quota Already set for project {}".format(project.name.encode('utf-8')))
            continue

        if int(json.loads(quota)["quota_set"][quota_name]) == -1:
            print("Quota for project {} set to unlimited, use apply-quota to lower")
            continue

        if int(quota_value) == -1 or int(quota_value) > int(json.loads(quota)["quota_set"][quota_name]):
            print("Increasing quota {} from {} to {} on project {}".format(quota_name, json.loads(quota)["quota_set"][quota_name], quota_value, project.name.encode('utf-8')))
            p9admin.project.apply_quota(client, project.id, quota_name, quota_value)
        else:
            if force:
                print("Forcing application of quota {} to {} on project {}".format(quota_name, quota_value, project.name.encode('utf-8')))
                p9admin.project.apply_quota(client, project.id, quota_name, quota_value)
            else:
                print("Application quota larger than new quota, use force to set lower.")


@project.command("apply-quota")
@click.option("--project-name", "-p")
@click.option("--quota-name", "-n")
@click.option("--quota-value", "-v")
def apply_quota(project_name, quota_name, quota_value):
    """

    Apply a quota to a project

    quota_name is one of:

    instances
    ram
    cores
    fixed_ips
    floating_ips
    injected_file_content_bytes
    injected_file_path_bytes
    injected_files
    key_pairs
    metadata_items
    security_groups
    security_group_rules
    server_groups
    server_group_members
    networks
    subnets
    routers
    root_gb

    quota_value is a number, -1 for unlimited


    """

    client = p9admin.OpenStackClient()

    if "OS_NOVA_URL" not in os.environ:
        sys.exit("OS_NOVA_URL environment variable must be set.  Check README.rst")

    project = client.project_by_name(project_name)

    validators.quota_name(quota_name)
    validators.quota_value(quota_name, quota_value)

    pprint.pprint(p9admin.project.apply_quota(client, project.id, quota_name, quota_value))


@project.command("get-quota")
@click.option("--project_name", "-p")
def get_quota(project_name):
    """ Get a list of quotas for a project """
    if "OS_NOVA_URL" not in os.environ:
        sys.exit("OS_NOVA_URL environment variable must be set.  Check README.rst")

    client = p9admin.OpenStackClient()
    project = client.project_by_name(project_name)

    pprint.pprint(p9admin.project.get_quota(client, project.id))


@project.command()
def list():
    """ Get a list of projects """
    client = p9admin.OpenStackClient()
    projects = client.projects()

    for project in projects:
        print(project.name)


@project.command()
@click.argument("names", metavar="NAME [NAME ...]", nargs=-1)
def delete(names):
    """Delete project(s) and the objects within"""
    client = p9admin.OpenStackClient()
    for name in names:
        p9admin.project.delete_project(client, name)


@project.command("ensure-ldap")
@click.argument("name")
@click.option("--group-cn", metavar="CN",
              help="The name of the group in LDAP. Defaults to NAME.")
@click.option("--uid", "-u", envvar='puppetpass_username')
@click.option("--password", "-p",
              prompt="puppetpass_password" not in os.environ,
              hide_input=True,
              default=os.environ.get('puppetpass_password', None))
def ensure_ldap(name, group_cn, uid, password):
    """Ensure a project exists based on an LDAP group"""

    if not uid:
        sys.exit("You must specify --uid USER to connect to LDAP")

    if group_cn is None:
        group_cn = name

    client = p9admin.OpenStackClient()

    client.logger.info("Ensuring actual project exists")
    project = p9admin.project.ensure_project(client, name)

    client.logger.info("Ensuring all users exist and have their own projects")

    users = p9admin.user.get_ldap_group_users(group_cn, uid, password)
    if not users:
        sys.exit("LDAP group {} doesn't contain any users".format(group_cn))

    client.ensure_users(users)
    user_ids = [user.user.id for user in users]
    client.ensure_project_members(project, user_ids, keep_others=False)

    print('Project "{}" [{}]'.format(project.name, project.id))
