# DAI_Alarm_Integrated.py
# coding=utf-8

import time, DAN, requests, random
import threading, sys
import tkinter as tk
import subprocess

# --- IoTtalk Configuration ---
ServerURL = 'http://140.114.77.93:9999'
Reg_addr = None
mac_addr = 'CD8600D38' + str(random.randint(100,999))
Reg_addr = mac_addr

DAN.profile['dm_name']='Dummy_Device'
DAN.profile['df_list']=['Dummy_Sensor', 'Dummy_Control']
DAN.profile['d_name']= "TWN_D."+ str( random.randint(100,999 ) ) +"_"+ DAN.profile['dm_name']

# Global variables for input thread and alarm control
gotInput = False
theInput = "haha"
allDead = False
current_pulled_message = "系統正常" # To display the message that triggered the alarm

# --- Alarm GUI Class ---
class AlarmGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🚨 警鈴系統")
        self.root.geometry("900x600")
        self.root.configure(bg="black")

        self.alarm_on = False
        self.flashing = False
        self.sound_process = None

        self.label = tk.Label(
            root,
            text="系統正常",
            font=("Arial", 90, "bold"),
            fg="green",
            bg="black"
        )
        self.label.pack(expand=True)

        self.message_label = tk.Label(
            root,
            text="",
            font=("Arial", 40),
            fg="white",
            bg="black"
        )
        self.message_label.pack(pady=20)

        self.button = tk.Button(
            root,
            text="Toggle Alarm (Manual)",
            command=self.toggle_alarm,
            font=("Arial", 48),
            bg="gray20",
            fg="white",
            relief="raised",
            padx=20,
            pady=10
        )
        self.button.pack(pady=30)

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def toggle_alarm(self, message=None):
        self.alarm_on = not self.alarm_on
        if self.alarm_on:
            self.label.config(text="ALARM!", fg="red")
            self.message_label.config(text=f"Message: {message}" if message else "手動觸發", fg="yellow")
            self.flashing = True
            threading.Thread(target=self.flash_label, daemon=True).start()
            threading.Thread(target=self.play_alarm_sound, daemon=True).start()
        else:
            self.flashing = False
            self.label.config(text="系統正常", fg="green")
            self.message_label.config(text="", fg="white") # Clear message when alarm is off
            if self.sound_process:
                self.sound_process.terminate()
                self.sound_process = None
            # Stop any flashing threads if they are still running
            # No need to explicitly stop, as `flashing` flag will handle it.

    def flash_label(self):
        while self.flashing:
            current_color = self.label.cget("fg")
            next_color = "yellow" if current_color == "red" else "red"
            self.label.config(fg=next_color)
            time.sleep(0.4)

    def play_alarm_sound(self):
        while self.flashing:
            try:
                self.sound_process = subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "./alarm.mp3"]
                )
                self.sound_process.wait()
            except FileNotFoundError:
                print("Error: ffplay not found. Please install FFmpeg.")
                self.flashing = False # Stop trying to play sound
                break
            except Exception as e:
                print(f"Error playing sound: {e}")
                self.flashing = False # Stop trying to play sound
                break
            if not self.flashing:
                break
            time.sleep(0.1)

    def on_closing(self):
        global allDead
        print("\nGUI closing...", flush=True)

        self.flashing = False
        if self.sound_process:
            self.sound_process.terminate()
            self.sound_process = None

        allDead = True

        time.sleep(0.5)

        self.root.destroy()

# --- IoTtalk Input Thread Function ---
def doRead():
    global gotInput, theInput, allDead # Declare them as global here!
    while True:
        while gotInput:
            time.sleep(0.1)
            continue
        try:
            theInput = input("Give me data (type 'quit' or 'exit' to end): ")
        except Exception:  # Handles KeyboardInterrupt
            allDead = True
            print("\n\nDeregister " + DAN.profile['d_name'] + " !!!\n", flush=True)
            DAN.deregister()
            sys.stdout = sys.__stdout__
            print(" Thread say Bye bye ---------------", flush=True)
            sys.exit()
        if theInput.lower() == 'quit' or theInput.lower() == "exit":
            allDead = True
        else:
            print(f"Will send {theInput}", end="   , ")
            gotInput = True # This modification requires 'gotInput' to be global
        if allDead:
            break

# --- Main IoTtalk and Alarm Logic ---
def iottalk_and_alarm_loop(alarm_app_instance):
    DAN.device_registration_with_retry(ServerURL, Reg_addr)
    print("dm_name is ", DAN.profile['dm_name'])
    print("Server is ", ServerURL)

    # Create a thread to do Input data from keyboard
    threadx = threading.Thread(target=doRead)
    threadx.daemon = True
    threadx.start()

    global gotInput, theInput, allDead
    while True:
        try:
            if allDead: break

            # Pull data from a device feature called "Dummy_Control"
            value1 = DAN.pull('Dummy_Control')
            if value1 != None:
                pulled_message = str(value1[0])
                print(f"Received from IoTtalk: {pulled_message}")
                # Check for specific message to toggle alarm
                if "alarm_on" in pulled_message.lower() and not alarm_app_instance.alarm_on:
                    display_message = pulled_message[len("alarm_on:"):].strip()
                    root.after(0, alarm_app_instance.toggle_alarm, display_message)
                elif "alarm_off" in pulled_message.lower() and alarm_app_instance.alarm_on:
                    display_message = pulled_message[len("alarm_off:"):].strip()
                    root.after(0, alarm_app_instance.toggle_alarm, display_message)
                
            # Push data to a device feature called "Dummy_Sensor"
            if gotInput:
                try:
                    value2 = theInput
                except:
                    value2 = 0
                if allDead: break
                gotInput = False
                DAN.push('Dummy_Sensor', value2, value2)

        except Exception as e:
            print(e)
            if str(e).find('mac_addr not found:') != -1:
                print('Reg_addr is not found. Try to re-register...')
                DAN.device_registration_with_retry(ServerURL, Reg_addr)
            else:
                print('Connection failed due to unknown reasons.')
                print("Error:", e)
                time.sleep(1)
        try:
            time.sleep(0.2)
        except KeyboardInterrupt:
            allDead = True
            break

    print("Exiting IoTtalk loop...")
    try:
        DAN.deregister()
    except Exception as e:
        print("Error during deregistration:", e)
    print("Bye ! --------------", flush=True)
    # sys.exit()

if __name__ == "__main__":
    root = tk.Tk()
    app = AlarmGUI(root)

    # Start the IoTtalk communication and alarm logic in a separate thread
    iottalk_thread = threading.Thread(target=iottalk_and_alarm_loop, args=(app,))
    iottalk_thread.daemon = True # Allow the main program to exit even if this thread is running
    iottalk_thread.start()

    root.mainloop() # Start the Tkinter event loop

    iottalk_thread.join(timeout=2)
    sys.exit()
