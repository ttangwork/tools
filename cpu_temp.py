import time
import psutil
import pystray
from PIL import Image, ImageDraw
from threading import Thread
import platform

def get_cpu_temperature():
    try:
        if platform.system() == "Windows":
            sensors = psutil.sensors_temperatures()
            if "coretemp" in sensors:
                return sensors["coretemp"][0].current
        elif platform.system() == "Darwin":  # macOS
            from subprocess import check_output
            output = check_output(["istats", "cpu", "temp"], text=True)
            temp_str = output.split(":")[1].strip().split("°")[0]
            return float(temp_str)
    except Exception:
        return None
    return None

def create_icon():
    icon_size = 64
    image = Image.new("RGB", (icon_size, icon_size), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 54, 54), fill="red")
    return image

def update_icon(icon):
    while True:
        temp = get_cpu_temperature()
        if temp is not None:
            icon.title = f"CPU Temp: {temp:.1f}°C"
        else:
            icon.title = "CPU Temp: N/A"
        time.sleep(5)

def main():
    image = create_icon()
    icon = pystray.Icon("cpu_temp", image, "CPU Temperature")
    
    thread = Thread(target=update_icon, args=(icon,), daemon=True)
    thread.start()
    
    icon.run()

if __name__ == "__main__":
    main()
