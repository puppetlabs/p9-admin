from __future__ import print_function
import click
import csv
import json
import os
import p9admin
import p9admin.validators as validators
import sys
from time import sleep

@click.group()
def project():
    """Manage projects."""
    pass


@project.command()
@click.argument("name")
def ensure(name):
    """
    Ensure a project exists.

    This will also ensure that the networks and other objects that should exist
    within the project do actually exist.
    """
    client = p9admin.OpenStackClient()
    project = p9admin.project.ensure_project(client, name, assume_complete=False)
    print('Project "{}" [{}]'.format(project.name, project.id))


@project.command()
@click.argument("name")
def show(name):
    """Show a project and the objects within."""
    p9admin.project.show_project(p9admin.OpenStackClient(), name)


@project.command("apply-quota-all")
@click.option("--quota-name", "-n")
@click.option("--quota-value", "-q")
@click.option("--force/--no-force", default=False)
@click.option("--defaults/--no-defaults", default=False)
def apply_quota_all(quota_name, quota_value, force=False, defaults=False):
    """
    Apply a quota to all projects in the environment.

    This will not lower quotas, only raise them.  Use --force to force all
    quotas to the new setting, even if that would mean lowering a quota.

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
    projects = client.projects()

    if "OS_NOVA_URL" not in os.environ:
        sys.exit("OS_NOVA_URL environment variable must be set.  Check README.md")

    client.logger.info("Starting application of quotas to all projects")

    if defaults:
        for project in projects:
            # This warns internally if a quota is larger than the default.
            p9admin.project.verified_apply_quota_defaults(client, project)

        sys.exit()

    validators.quota_name(quota_name)
    validators.quota_value(quota_name, quota_value)

    for project in projects:
        try:
            p9admin.project.verified_apply_quota(
                client, project, quota_name, quota_value)
        except p9admin.RequiresForceError:
            client.logger.warning(
                "Skipping project %s because its quota %s is greater than"
                " the requested quota. Use apply-quota --force.",
                project, project.name)


@project.command("apply-quota")
@click.option("--project-name", "-p")
@click.option("--quota-name", "-n")
@click.option("--quota-value", "-q")
@click.option("--defaults/--no-defaults", default=False)
def apply_quota(project_name, quota_name, quota_value, defaults):
    """
    Apply a quota to a project.

    --quota-name is one of:

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

    quota-value is a number. Use -1 for unlimited.
    """

    client = p9admin.OpenStackClient()

    if "OS_NOVA_URL" not in os.environ:
        sys.exit("OS_NOVA_URL environment variable must be set.  Check README.md")

    project = client.project_by_name(project_name)

    if defaults:
        if quota_name or quota_value:
            sys.exit("Can't use --defaults with --quota-name or --quota-value")
        # This warns internally if a quota is larger than the default.
        p9admin.project.verified_apply_quota_defaults(client, project.id)
        sys.exit()

    validators.quota_name(quota_name)
    validators.quota_value(quota_name, quota_value)

    try:
        quotas = p9admin.project.verified_apply_quota(client, project.id, quota_name, quota_value))
    except p9admin.RequiresForceError:
        client.logger.fatal(
            "Not setting quota %s because it is greater than the requested"
            " quota. Use --force.", project, project.name)

    if quotas:
        quotas_string = json.dumps(
            quotas,
            sort_keys=True,
            indent=4,
            separators=(',', ': '))
        print(quotas_string)


@project.command("get-quota")
@click.option("--project_name", "-p")
def get_quota(project_name):
    """Get a list of quotas for a project."""
    if "OS_NOVA_URL" not in os.environ:
        sys.exit("OS_NOVA_URL environment variable must be set.  Check README.md")

    client = p9admin.OpenStackClient()
    project = client.project_by_name(project_name)

    quotas = p9admin.project.get_quota(client, project.id)
    quotas_string = json.dumps(
        quotas,
        sort_keys=True,
        indent=4,
        separators=(',', ': '))
    print(quotas_string)


@project.command()
def list():
    """Get a list of projects."""
    client = p9admin.OpenStackClient()
    projects = client.projects()

    for project in projects:
        print(project.name)


@project.command()
@click.argument("names", metavar="NAME [NAME ...]", nargs=-1)
def delete(names):
    """Delete project(s) and the objects within."""
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
    """Ensure a project exists based on an LDAP group."""

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


@project.command()
def stats():
    """
    Get information about usage of all projects.

    This outputs CSV.
    """
    client = p9admin.OpenStackClient()
    projects = client.projects()

    writer = csv.writer(sys.stdout)
    writer.writerow([
        "project_id",
        "project_name",
        "count_servers",
        "count_servers_on",
        "count_volumes",
        "size_volumes",
        "count_volumes_inuse",
        "size_volumes_inuse",
    ])

    for project in projects:
        stats = p9admin.project.get_stats(client, project)
        writer.writerow([project.id, project.name] + stats)
