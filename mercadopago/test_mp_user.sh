# Get access token
# Your client id and secret.
CLIENT_ID=
CLIENT_SECRET=
SITE_ID=MLA

AT=$(curl -s -X POST -H 'content-type: application/x-www-form-urlencoded' \
	'https://api.mercadopago.com/oauth/token' \
	-d 'grant_type=client_credentials' \
	-d "client_id=$CLIENT_ID" \
	-d "client_secret=$CLIENT_SECRET" \
	| grep -o '"access_token":"[^"]*"' \
	| sed -n 's/.*"access_token":"\(.*\)"/\1/p')

JSON=$(curl -X POST \
	-H "Content-Type: application/json" \
	"https://api.mercadopago.com/users/test_user?access_token=$AT" \
	-d "{'site_id':'$SITE_ID'}")

echo $JSON >> test_users.json

