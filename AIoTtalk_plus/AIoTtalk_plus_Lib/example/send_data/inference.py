from ultralytics import YOLO
import time, DAN, requests, random
import threading, sys
import config
import requests
import time
import os

OFLServer = config.OFLServer
OFLServerPort = config.OFLServerPort

def download_weights(client_id, weight_path):
    """Download the model weights from the OFL server."""

    url = f'http://{OFLServer}:{OFLServerPort}/OFL_server/model_weights'
    headers = {'Client-ID': client_id, 'Inference': 'true'}

    try:
        response = requests.post(url, headers=headers, stream=True)

        content_type = response.headers.get('Content-Type', '')
        if 'application/json' in content_type:
            json_data = response.json()
            if not json_data.get('download', False):
                print("No new model to download.")
                return None

        with open(weight_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
        print(f"Downloaded model saved as: {weight_path}")
        return weight_path

    except Exception as e:
        print(f"Error downloading weights: {e}")
        return None

# --- YOLO Object Detection Function ---
def check_for_object(weight_path, image_path, target_class_name):
    try:
        model = YOLO(weight_path)
    except Exception as e:
        print(f"Error while loading weights: {e}. Ensure the weight file is correct.")
        print(f"Weight file path: {weight_path}")
        return False

    try:
        results = model(image_path)
    except Exception as e:
        import traceback
        print(f"Error during inference: {e}. Check if the image path is correct.")
        traceback.print_exc()
        print(f"Image path: {image_path}")
        return False

    for r in results:
        class_names = r.names
        detected_class_ids = r.boxes.cls.tolist()
        detected_class_names = [class_names[int(class_id)] for class_id in detected_class_ids]
        print(detected_class_names)
        if target_class_name in detected_class_names:
            # print("Here detected!!!")
            return True
    return False


gotInput = False
theInput = "haha"
allDead = False

# def doRead():
#     global gotInput, theInput, allDead
#     while True:
#         while gotInput:
#             time.sleep(0.1)
#             continue
#         try:
#             theInput = input("Give me data: ")
#         except Exception:
#             allDead = True
#             print("\n\nDeregister " + DAN.profile['d_name'] + " !!!\n", flush=True)
#             DAN.deregister()
#             sys.stdout = sys.__stdout__
#             print(" Thread say Bye bye ---------------", flush=True)
#             sys.exit()
#         if theInput =='quit' or theInput == "exit":
#             allDead = True
#         else:
#             print("Will send " + theInput, end="   , ")
#             gotInput=True
#         if allDead: break

def start_conn(client_id, weight_file, img_list, lock, stop_event):

    # --- IoTtalk Device Setup ---
    ServerURL = 'http://140.114.77.93:9999'
    Reg_addr = None
    mac_addr = 'CD8600D38' + str( random.randint(100,999 ) )
    Reg_addr = mac_addr

    DAN.profile['dm_name']='Dummy_Device'
    DAN.profile['df_list']=['Dummy_Sensor', 'Dummy_Control']
    DAN.profile['d_name']= "TWN_D."+ str( random.randint(100,999 ) ) +"_"+ DAN.profile['dm_name']

    DAN.device_registration_with_retry(ServerURL, Reg_addr, stop_event)
    print("dm_name is ", DAN.profile['dm_name'])
    print("Server is ", ServerURL)

    # threadx = threading.Thread(target=doRead)
    # threadx.daemon = True
    # threadx.start()

    script_dir = os.path.dirname(os.path.abspath(__file__))  # Directory of the current script
    weight_filename = weight_file + '.pt' if not weight_file.endswith('.pt') else weight_file
    weight_path = os.path.join(script_dir, weight_filename)

    cnt = 0
    download_weights(client_id, weight_path)
    while not stop_event.is_set():
        while not img_list:
            time.sleep(1)
        if cnt / 20 > 1:
            print("Checking for model update...")
            download_weights(client_id, weight_path)
            cnt %= 20
        try:
            if allDead:
                break

            value1 = DAN.pull('Dummy_Control')
            if value1 is not None:
                print(value1[0])
                
            time.sleep(10)
            
            # print("start")

            # Check for object in the image and send alarm message
            object = config.object
            object_detected = False
            with lock:
                if img_list:
                    img_src = img_list
                    cnt += len(img_src)
                    print(f"Processing {len(img_src)} images. Now cnt: {cnt}")
                    object_detected = check_for_object(weight_path, img_src, object)
                    img_list.clear()

            if object_detected:
                alarm_message = f"alarm_on {object.upper()} HERE!!!"
                print(f"Sending: {alarm_message}")
                try:
                    DAN.push('Dummy_Sensor', alarm_message, alarm_message)
                except Exception as e:
                    print(f"Failed to send data: {e}")
                time.sleep(5)
                

        except Exception as e:
            print(e)
            # if str(e).find('mac_addr not found:') != -1:
            #     print('Reg_addr is not found. Try to re-register...')
            #     DAN.device_registration_with_retry(ServerURL, Reg_addr)
            # else:
            #     print('Connection failed due to unknown reasons.')
            #     time.sleep(1)

        try:
            time.sleep(0.2)
        except KeyboardInterrupt:
            break

    time.sleep(0.25)
    try:
        DAN.deregister()
    except Exception as e:
        print("===")
    print("Bye ! --------------", flush=True)
    sys.exit()


# --- Main Loop ---
if __name__ == "__main__":

    default_img = '/home/wmnet/chuchun/OFL/client/datasets/VisDrone_t/VisDrone2019-DET-train/images/0000013_00465_d_0000067.jpg'

    img_src = sys.argv[1] if len(sys.argv) > 1 else default_img
    start_conn(img_src)