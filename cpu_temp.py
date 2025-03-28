import time
import psutil
import pystray
from PIL import Image, ImageDraw
from threading import Thread

def get_cpu_temperature():
    try:
        sensors = psutil.sensors_temperatures()
        if "coretemp" in sensors:
            return sensors["coretemp"][0].current
    except Exception:
        return None
    return None

def create_icon():
    icon_size = 64
    image = Image.new("RGB", (icon_size, icon_size), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 54, 54), fill="red")
    return image

def update_icon(icon, stop_flag):
    while not stop_flag.is_set():
        temp = get_cpu_temperature()
        if temp is not None:
            icon.title = f"CPU Temp: {temp:.1f}°C"
        else:
            icon.title = "CPU Temp: N/A"
        time.sleep(5)

def quit_app(icon, stop_flag):
    stop_flag.set()
    icon.stop()

def main():
    image = create_icon()
    icon = pystray.Icon("cpu_temp", image, "CPU Temperature")
    stop_flag = Thread(target=lambda: None)  # Dummy thread to hold stop flag
    stop_flag.is_set = lambda: False
    stop_flag.set = lambda: setattr(stop_flag, "is_set", lambda: True)
    
    thread = Thread(target=update_icon, args=(icon, stop_flag), daemon=True)
    thread.start()
    
    icon.menu = pystray.Menu(pystray.MenuItem("Quit", lambda icon, item: quit_app(icon, stop_flag)))
    icon.run()

if __name__ == "__main__":
    main()
