from PIL import Image
import os
D = "src/icons"
spec = {  # name: (source, colour)
 "add": ("add", (30,140,50)), "resume": ("resume", (30,140,50)), "stop": ("stop", (225,130,20)),
 "stopall": ("stopall", (210,50,45)), "delete": ("delete", (200,50,45)), "deletedone": ("deletedone", (200,50,45)),
 "options": ("options", (70,95,140)), "scheduler": ("scheduler", (40,110,190)),
 "startq": ("startq", (30,140,50)), "stopq": ("stopq", (210,50,45)),
 "open": ("open", (40,110,190)), "folder": ("folder", (200,150,30)), "link": ("link", (70,95,140)),
}
def tint(src, rgb, size=32, a=1.0):
    im = Image.open(f"{D}/{src}_light.png").convert("RGBA").resize((size, size), Image.LANCZOS)
    r, g, b, al = im.split()
    out = Image.new("RGBA", im.size, rgb + (0,)); out.putalpha(al.point(lambda v: int(v * a)))
    return out
for k, (s, c) in spec.items():
    tint(s, c).save(f"{D}/tb_{k}.png")
    tint(s, (170,170,170), a=.8).save(f"{D}/tb_{k}_off.png")
# small 16px icons for sidebar/menu/list
for k in ["all","finished","unfinished","startq","folder"]:
    tint(k, (70,95,140), 16).save(f"{D}/s_{k}.png")
for c in ["Videos","Music","Documents","Images","Design","Compressed","Programs","General"]:
    Image.open(f"{D}/cat_{c}_light.png").convert("RGBA").resize((16,16), Image.LANCZOS).save(f"{D}/s_cat_{c}.png")
    Image.open(f"{D}/cat_{c}_light.png").convert("RGBA").resize((18,18), Image.LANCZOS).save(f"{D}/r_cat_{c}.png")
# dark-mode variants: brighter tints for the toolbar (tbd_) and the small tree icons (sd_)
dark = {"add": (80,200,120), "resume": (80,200,120), "stop": (245,170,60), "stopall": (240,100,95), "delete": (235,105,100),
        "deletedone": (235,105,100), "options": (150,170,230), "scheduler": (100,170,245), "startq": (80,200,120),
        "stopq": (240,100,95), "open": (100,170,245), "folder": (235,190,80), "link": (150,170,230)}
for k, c in dark.items():
    s_ = spec[k][0]
    tint(s_, c).save(f"{D}/tbd_{k}.png")
    tint(s_, (110,110,110), a=.9).save(f"{D}/tbd_{k}_off.png")
for k in ["all","finished","unfinished","startq","folder"]:
    tint(k, (170,185,225), 16).save(f"{D}/sd_{k}.png")
print(len(os.listdir(D)))
