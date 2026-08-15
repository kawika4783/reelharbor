import re
def format_duration(seconds):
    if seconds is None: return "Unknown"
    seconds=max(0,int(seconds)); h,r=divmod(seconds,3600); m,s=divmod(r,60); return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
def format_size(value,estimated=False):
    if value is None:return "Unknown"
    n=float(value); units=["B","KB","MB","GB","TB"]; i=0
    while n>=1024 and i<len(units)-1:n/=1024;i+=1
    value=f"{n:.0f}" if i<2 else f"{n:.1f}"; return f"{'~' if estimated else ''}{value} {units[i]}"
def sanitize_filename(value):
    value=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',value).strip(' .'); value=re.sub(r'\s+',' ',value); return (value[:180] or "untitled")
