import time
import datetime

t = 134162696771240000
unix = (t / 10000000) - 11644473600
print(datetime.datetime.fromtimestamp(unix))

now = time.time()
print(datetime.datetime.fromtimestamp(now))
