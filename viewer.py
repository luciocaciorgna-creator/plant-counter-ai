"""Visor de fotos con zoom y desplazamiento táctil para Streamlit.

- Pellizcar con dos dedos (o rueda del mouse, o botones ＋ / －) para hacer zoom.
- Arrastrar con un dedo (o con el mouse) para moverse cuando hay zoom.
- Con zoom 1x, un dedo desplaza la página (no queda "trabada" en la foto).
- Botón "👁" para alternar entre foto procesada y original en la misma posición.
- Un toque devuelve las coordenadas en píxeles de la foto (para agregar/quitar plantas).

No necesita archivos extra: el HTML se escribe solo en una carpeta temporal.
"""
import base64
import tempfile
from pathlib import Path

import cv2
import streamlit.components.v1 as components

_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>
html,body{margin:0;padding:0;background:transparent;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
#v{position:relative;width:100%;overflow:hidden;background:#1b1b1b;border-radius:8px;touch-action:pan-y;
   user-select:none;-webkit-user-select:none;-webkit-touch-callout:none}
#im{position:absolute;left:0;top:0;transform-origin:0 0;will-change:transform;pointer-events:none;max-width:none;
    -webkit-user-drag:none}
#bar{position:absolute;top:8px;right:8px;display:flex;gap:6px;z-index:5}
#bar button{min-width:44px;height:44px;border:0;border-radius:8px;background:rgba(0,0,0,.62);color:#fff;
            font-size:22px;line-height:1;cursor:pointer;padding:0 10px}
#bar button.t{font-size:14px;font-weight:600}
#info{position:absolute;left:8px;bottom:8px;background:rgba(0,0,0,.55);color:#fff;font-size:12px;
      padding:3px 8px;border-radius:6px;z-index:5;pointer-events:none}
.flash{position:absolute;width:30px;height:30px;margin:-15px 0 0 -15px;border:3px solid #ffe600;
       border-radius:50%;pointer-events:none;animation:f .9s forwards;z-index:4}
@keyframes f{to{opacity:0;transform:scale(1.9)}}
</style></head><body>
<div id="v"><img id="im" alt="">
<div id="bar"><button id="bo" class="t">👁 Original</button><button id="bm" aria-label="Alejar">－</button>
<button id="bp" aria-label="Acercar">＋</button><button id="br" aria-label="Restablecer">⟲</button></div>
<div id="info"></div></div>
<script>
function post(type, extra){ window.parent.postMessage(Object.assign({isStreamlitMessage:true,type:type}, extra||{}), "*"); }
var v=document.getElementById('v'), im=document.getElementById('im'), info=document.getElementById('info'),
    bo=document.getElementById('bo');
var A={orig:"",proc:"",altura:560,taps:false,reset_key:null};
var showOrig=false, s=1, tx=0, ty=0, W=0, H=0, curSrc="", started=false;
var ptrs=new Map(), g=null;

function cw(){ return v.clientWidth; }
function fit(){ return W ? Math.min(cw()/W, A.altura/H) : 1; }
function clampView(){
  var k=fit()*s, w=W*k, h=H*k, cwid=cw(), chh=A.altura;
  tx = (w<=cwid) ? (cwid-w)/2 : Math.min(0, Math.max(cwid-w, tx));
  ty = (h<=chh)  ? (chh-h)/2  : Math.min(0, Math.max(chh-h, ty));
}
function apply(){
  if(!W) return;
  clampView();
  var k=fit()*s;
  im.style.width=W+"px"; im.style.height=H+"px";
  im.style.transform="translate("+tx+"px,"+ty+"px) scale("+k+")";
  v.style.touchAction = s>1.01 ? "none" : "pan-y";
  info.textContent=(showOrig?"Original":"Procesada")+" · "+s.toFixed(1)+"x";
  bo.textContent = showOrig ? "👁 Procesada" : "👁 Original";
}
function resetView(){ s=1; tx=0; ty=0; apply(); }
function zoomAt(cx,cy,ns){
  ns=Math.max(1,Math.min(10,ns));
  var k0=fit()*s, px=(cx-tx)/k0, py=(cy-ty)/k0;
  s=ns; var k=fit()*s; tx=cx-px*k; ty=cy-py*k; apply();
}
function setImg(){
  var src = showOrig ? A.orig : A.proc;
  if(src && src!==curSrc){ curSrc=src; im.src=src; }
}
im.onload=function(){
  if(im.naturalWidth!==W || im.naturalHeight!==H){ W=im.naturalWidth; H=im.naturalHeight; resetView(); }
  else apply();
};

window.addEventListener("message", function(ev){
  var d=ev.data;
  if(!d || d.type!=="streamlit:render") return;
  var a=d.args||{}, prev=started ? A.reset_key : a.reset_key;
  A=a; A.altura=a.altura||560; started=true;
  v.style.height=A.altura+"px";
  if(prev!==a.reset_key){ showOrig=false; s=1; tx=0; ty=0; curSrc=""; }
  setImg(); apply();
  post("streamlit:setFrameHeight",{height:A.altura+2});
});

function rect(){ return v.getBoundingClientRect(); }

v.addEventListener("pointerdown", function(e){
  if(e.target.closest && e.target.closest("#bar")) return;
  try{ v.setPointerCapture(e.pointerId); }catch(_){}
  ptrs.set(e.pointerId,{x:e.clientX,y:e.clientY});
  var r=rect();
  if(ptrs.size===1){
    g={mode:"one",sx:e.clientX,sy:e.clientY,t0:Date.now(),tx0:tx,ty0:ty,moved:false,multi:false};
  } else if(ptrs.size===2){
    var p=Array.from(ptrs.values()), a=p[0], b=p[1];
    var cx=(a.x+b.x)/2-r.left, cy=(a.y+b.y)/2-r.top, d=Math.hypot(a.x-b.x,a.y-b.y)||1, k0=fit()*s;
    g={mode:"two",d0:d,s0:s,px:(cx-tx)/k0,py:(cy-ty)/k0,multi:true,moved:true};
  }
});

v.addEventListener("pointermove", function(e){
  if(!ptrs.has(e.pointerId)) return;
  ptrs.set(e.pointerId,{x:e.clientX,y:e.clientY});
  if(!g) return;
  var r=rect();
  if(g.mode==="one"){
    var dx=e.clientX-g.sx, dy=e.clientY-g.sy;
    if(Math.abs(dx)>8 || Math.abs(dy)>8) g.moved=true;
    if(g.moved && s>1.01){ tx=g.tx0+dx; ty=g.ty0+dy; apply(); }
  } else if(g.mode==="two" && ptrs.size>=2){
    var p=Array.from(ptrs.values()), a=p[0], b=p[1];
    var cx=(a.x+b.x)/2-r.left, cy=(a.y+b.y)/2-r.top, d=Math.hypot(a.x-b.x,a.y-b.y)||1;
    var ns=Math.max(1,Math.min(10,g.s0*d/g.d0));
    var k=fit()*ns; s=ns; tx=cx-g.px*k; ty=cy-g.py*k; apply();
  }
});

function endPtr(e, cancelled){
  if(!ptrs.has(e.pointerId)) return;
  var wasTap = g && g.mode==="one" && !g.moved && !g.multi && !cancelled && (Date.now()-g.t0)<600;
  ptrs.delete(e.pointerId);
  if(wasTap && A.taps && W){
    var r=rect(), k=fit()*s, x=(e.clientX-r.left-tx)/k, y=(e.clientY-r.top-ty)/k;
    if(x>=0 && y>=0 && x<=W && y<=H){
      var f=document.createElement('div'); f.className='flash';
      f.style.left=(e.clientX-r.left)+"px"; f.style.top=(e.clientY-r.top)+"px";
      v.appendChild(f); setTimeout(function(){ if(f.parentNode) f.parentNode.removeChild(f); }, 950);
      post("streamlit:setComponentValue",{value:{x:x,y:y,t:Date.now()},dataType:"json"});
    }
  }
  if(ptrs.size===0){ g=null; }
  else if(ptrs.size===1){
    var q=Array.from(ptrs.values())[0];
    g={mode:"one",sx:q.x,sy:q.y,t0:Date.now(),tx0:tx,ty0:ty,moved:true,multi:true};
  }
}
v.addEventListener("pointerup", function(e){ endPtr(e,false); });
v.addEventListener("pointercancel", function(e){ endPtr(e,true); });

v.addEventListener("wheel", function(e){
  e.preventDefault();
  var r=rect();
  zoomAt(e.clientX-r.left, e.clientY-r.top, s*(e.deltaY<0 ? 1.18 : 1/1.18));
}, {passive:false});

document.getElementById('bp').onclick=function(){ zoomAt(cw()/2, A.altura/2, s*1.6); };
document.getElementById('bm').onclick=function(){ zoomAt(cw()/2, A.altura/2, s/1.6); };
document.getElementById('br').onclick=function(){ resetView(); };
bo.onclick=function(){ showOrig=!showOrig; setImg(); apply(); };
window.addEventListener("resize", apply);

post("streamlit:componentReady",{apiVersion:1});
post("streamlit:setFrameHeight",{height:562});
</script></body></html>
"""

_DIR = Path(tempfile.gettempdir()) / "plant_counter_viewer"
_comp = None


def _componente():
    global _comp
    if _comp is None:
        _DIR.mkdir(parents=True, exist_ok=True)
        (_DIR / "index.html").write_text(_HTML, encoding="utf-8")
        _comp = components.declare_component("foto_viewer", path=str(_DIR))
    return _comp


def _b64(img_bgr, calidad=85):
    ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, calidad])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def foto_viewer(original_bgr, procesada_bgr, altura, taps, reset_key, key):
    """Muestra el visor. Devuelve {'x','y','t'} cuando se toca la foto (si taps=True), si no None.

    x, y están en píxeles de la foto (la misma que se analiza).
    """
    return _componente()(orig=_b64(original_bgr), proc=_b64(procesada_bgr), altura=int(altura),
                         taps=bool(taps), reset_key=str(reset_key), key=key, default=None)
