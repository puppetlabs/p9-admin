if [[ "$(docker images -q p9-admin 2> /dev/null)" != "" ]]; then
  img='p9-admin'
else
  img='artifactory.delivery.puppetlabs.net/infracore/p9-admin:latest'
fi

docker run -it --rm \
-e p9_user \
-e p9_password \
-e OS_AUTH_URL \
-e OS_NOVA_URL \
-e OS_IDENTITY_API_VERSION \
-e OS_REGION_NAME \
-e OS_USERNAME \
-e OS_PASSWORD \
-e OS_USER_DOMAIN_ID \
-e OS_PROJECT_NAME \
-e OS_PROJECT_DOMAIN_ID \
$img "$@"
