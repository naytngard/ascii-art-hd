import math, sys
import numpy as np
from PIL import Image
sp = sys.argv[1]
# synthetic image: lit sphere + red dots on dark bg
W=H=600
y,x = np.mgrid[0:H,0:W]; cx=cy=300; r=210
d2=(x-cx)**2+(y-cy)**2
img=np.zeros((H,W,3),np.float32)
m=d2<r*r
nz=np.sqrt(np.maximum(0,1-d2/(r*r)))
nx=(x-cx)/r; ny=(y-cy)/r
light=np.clip(-0.5*nx-0.6*ny+0.65*nz,0,1)
img[m]=(np.stack([0.9*light,0.75*light,0.4*light],-1))[m]
for k in range(8):
    a=k*math.pi/4; px=int(300+330*0.9*math.cos(a)*0.85); py=int(300+300*math.sin(a))
    img[max(0,py-14):py+14, max(0,px-14):px+14]=[0.8,0.1,0.1]
Image.fromarray((img*255).astype(np.uint8)).save(sp+"/t_img.png")
# gif: moving ball
fr=[]
for k in range(10):
    im=np.zeros((200,300,3),np.uint8); yy,xx=np.mgrid[0:200,0:300]
    c=40+k*24; mm=(xx-c)**2+(yy-100)**2<40*40
    im[mm]=[60,200,120]; fr.append(Image.fromarray(im))
fr[0].save(sp+"/t_anim.gif",save_all=True,append_images=fr[1:],duration=80,loop=0)
# torus obj
R,rr=1.0,0.38; n,m2=40,20; verts=[];faces=[]
for i in range(n):
    for j in range(m2):
        u=2*math.pi*i/n; v=2*math.pi*j/m2
        verts.append(((R+rr*math.cos(v))*math.cos(u), rr*math.sin(v), (R+rr*math.cos(v))*math.sin(u)))
for i in range(n):
    for j in range(m2):
        a=i*m2+j; b=((i+1)%n)*m2+j; c=((i+1)%n)*m2+(j+1)%m2; d=i*m2+(j+1)%m2
        faces.append((a,b,c,d))
with open(sp+"/t_torus.obj","w") as f:
    for v in verts: f.write("v %f %f %f\n"%v)
    for q in faces: f.write("f %d %d %d %d\n"%tuple(i+1 for i in q))