#!/usr/bin/env python3
import time
from datetime import datetime

while True:
    print(datetime.now().strftime("%H:%M:%S"))
    time.sleep(1)
