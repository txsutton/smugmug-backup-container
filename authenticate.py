from rauth import OAuth1Service
import os

def authenticate():
    print("--- SmugMug Professional Sync Setup ---")
    
    # Collect all needed info upfront
    api_key = input("1. Enter SmugMug API Key: ").strip()
    api_secret = input("2. Enter SmugMug API Secret: ").strip()
    nickname = input("3. Enter your SmugMug Nickname: ").strip()

    service = OAuth1Service(
        name='smugmug-sync',
        consumer_key=api_key,
        consumer_secret=api_secret,
        request_token_url='https://api.smugmug.com/services/oauth/1.0a/getRequestToken',
        access_token_url='https://api.smugmug.com/services/oauth/1.0a/getAccessToken',
        authorize_url='https://api.smugmug.com/services/oauth/1.0a/authorize',
        base_url='https://api.smugmug.com/api/v2/'
    )

    # OAuth Flow
    rt, rts = service.get_request_token(params={'oauth_callback': 'oob'})
    auth_url = service.get_authorize_url(rt)
    
    print(f"\n4. Open this URL in your browser: {auth_url}")
    verifier = input("5. Enter the 6-digit PIN provided by SmugMug: ").strip()
    
    try:
        session = service.get_auth_session(rt, rts, data={'oauth_verifier': verifier})

        # Write the complete .env file
        with open(".env", "w") as f:
            f.writelines([
                f"API_KEY={api_key}\n",
                f"API_SECRET={api_secret}\n",
                f"ACCESS_TOKEN={session.access_token}\n",
                f"ACCESS_SECRET={session.access_token_secret}\n",
                f"NICKNAME={nickname}\n"
            ])

        print("\n✅ SUCCESS: .env file has been fully generated!")
        print("You can now build and run your Docker container.")
        
    except Exception as e:
        print(f"\n❌ Error during authentication: {e}")

if __name__ == "__main__":
    authenticate()
