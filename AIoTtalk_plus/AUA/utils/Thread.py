import threading

def run_in_thread(function):
    def wrapper(*args, **kwargs):
        #print("start thread----------")
        thread = threading.Thread(target=function, args=args)
        thread.start()
    return wrapper
