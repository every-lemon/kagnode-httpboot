"""Start the private routed console against an existing HTTP Boot authority."""
import argparse
from pathlib import Path
from server_console import existing_authority,serve

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,default=Path('/var/lib/kagnode/httpboot-server'))
    parser.add_argument('--port',type=int,default=8084)
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('Port must be between 1 and 65535')
    authority=existing_authority(args.state/'authority.sqlite3')
    serve(authority,args.state/'pki',args.port,credential_name='web-console-token')

if __name__=='__main__':main()
