import sys
if sys.prefix == '/usr':
    sys.real_prefix = sys.prefix
    sys.prefix = sys.exec_prefix = '/home/kaushalraj/adaptive_bridge_ws/install/adaptive_bridge'
