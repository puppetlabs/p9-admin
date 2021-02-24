import sys

def quota_name(quota_name):
    quotas = [
        "instances",
        "ram",
        "cores",
        "fixed_ips",
        "floating_ips",
        "injected_file_content_bytes",
        "injected_file_path_bytes",
        "injected_files",
        "key_pairs",
        "metadata_items",
        "security_groups",
        "security_group_rules",
        "server_groups",
        "server_group_members",
        "networks",
        "subnets",
        "routers",
        "root_gb",
    ]

    if quota_name not in quotas:
        sys.exit('Quota "{}" invalid, try one of {}'.format(quota_name, quotas))


def quota_value(quota_name, quota_value):
    if quota_value > 1000000:
        sys.exit("A setting of '{}' for {} seems a bit unreasonable, don't you think?".format(quota_value, quota_name))
