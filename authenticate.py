from rauth import OAuth1Service
import os

def authenticate():
    api_key = input("Enter SmugMug API Key: ")
    api_secret = input("Enter SmugMug API Secret: ")

    service = OAuth1Service(
        name='smugmug-sync',
        consumer_key=api_key,
        consumer_secret=api_secret,
        request_token_url='https://api.smugmug.com/services/oauth/1.0a/getRequestToken',
        access_token_url='https://api.smugmug.com/services/oauth/1.0a/getAccessToken',
        authorize_url='https://api.smugmug.com/services/oauth/1.0a/authorize',
        base_url='https://api.smugmug.com/api/v2/'
    )

    rt, rts = service.get_request_token(params={'oauth_callback': 'oob'})
    auth_url = service.get_authorize_url(rt)
    print(f"\n1. Go to: {auth_url}")
    print("2. Authorize the app and copy the 6-digit PIN.")
    
    verifier = input("\n3. Enter the PIN: ")
    session = service.get_auth_session(rt, rts, data={'oauth_verifier': verifier})

    print("\n--- AUTHENTICATION SUCCESSFUL ---")
    print(f"USER_TOKEN: {session.access_token}")
    print(f"USER_SECRET: {session.access_token_secret}")
    print("----------------------------------")

if __name__ == "__main__":
    authenticate()
