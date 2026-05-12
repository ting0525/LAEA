import requests
import json

OFLServer = "140.114.77.72"
OFLServerPort = "3002"

def request_join(client_name, model_name, dataset_format):
    url = f'http://{OFLServer}:{OFLServerPort}/OFL_server/join_request'
    headers = {'Content-Type': 'application/json'}
    post_data = {'NAME': client_name, 'EDGE_SITE': 'site-hsinchu', 'MODEL_NAME': model_name, 'DATASET_FORMAT': dataset_format}
    try:
        response = requests.post(url, json = post_data, headers=headers)
        if response.status_code == 200:
            print("Join request successful")
            response_data = json.loads(response.text)
            client_id = response_data.get("client_id")
            sip_account = response_data.get("sip_account")
            print(f"Client ID: {client_id}, SIP Account: {sip_account}")
            return client_id, sip_account
        else:
            print(f"Join request failed: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"request_join error: {e}")
        return None

def request_delete(client_id, sip_account):

    print("HERE in request_delete")
    print(sip_account)

    url = f'http://{OFLServer}:{OFLServerPort}/OFL_server/terminate_request'
    headers = {'Content-Type': 'application/json', 'Client-ID': client_id}
    post_data = {'SIP_ACCOUNT': sip_account}
    try:
        response = requests.post(url, json=post_data, headers=headers, timeout=5)
        if response.status_code == 200:
            print("Delete request successful")
            # print(response.text)
        else:
            print(f"Delete request failed: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"request_delete error: {e}")