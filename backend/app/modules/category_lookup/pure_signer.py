"""Offline Python port of AngelToms utils.js (1.0.1.19-fix.01).
Copyright AngelToms. SPDX-License-Identifier: Apache-2.0
Port: OpenAI, 2026-11-03. See README for limitations.
No browser, Node.js, network or third-party Python dependency is used.
This reproduces the public JS's release path, including documented quirks.
"""
import base64
import random
import time
from dataclasses import dataclass

MASK = 0xffffffff
S3 = 'ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe'
S4 = 'Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe'
STANDARD = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

def _rot(x, n):
    n %= 32
    return ((x << n) | (x >> ((32-n) % 32))) & MASK

def _units(s):
    data = s.encode('utf-16-be', errors='surrogatepass')
    return [int.from_bytes(data[i:i+2], 'big') for i in range(0, len(data), 2)]

def _js_string_bytes(s):
    # Source sm3.js uses minimally sized big-endian UTF-16 units, NOT UTF-8.
    out = bytearray()
    for ch in _units(s):
        if ch > 255:
            out.append(ch >> 8)
        out.append(ch & 255)
    return bytes(out)

def sm3(data):
    """Standard SM3 bytes digest; strings follow the source JS byte conversion."""
    data = _js_string_bytes(data) if isinstance(data, str) else bytes(data)
    length = len(data) * 8
    msg = data + b'\x80'
    msg += b'\0' * ((56-len(msg)) % 64) + length.to_bytes(8, 'big')
    v = [0x7380166f,0x4914b2b9,0x172442d7,0xda8a0600,0xa96f30bc,0x163138aa,0xe38dee4d,0xb0fb0e4e]
    for start in range(0, len(msg), 64):
        block = msg[start:start+64]
        w = [int.from_bytes(block[i:i+4], 'big') for i in range(0,64,4)]
        for j in range(16,68):
            x = w[j-16] ^ w[j-9] ^ _rot(w[j-3],15)
            w.append((x ^ _rot(x,15) ^ _rot(x,23) ^ _rot(w[j-13],7) ^ w[j-6]) & MASK)
        a,b,c,d,e,f,g,h = v
        for j in range(64):
            ss1 = _rot((_rot(a,12)+e+_rot(0x79cc4519 if j<16 else 0x7a879d8a,j)) & MASK,7)
            ss2 = ss1 ^ _rot(a,12)
            ff = a ^ b ^ c if j<16 else (a&b) | (a&c) | (b&c)
            gg = e ^ f ^ g if j<16 else (e&f) | ((~e)&g)
            t1 = (ff+d+ss2+(w[j]^w[j+4])) & MASK
            t2 = (gg+h+ss1+w[j]) & MASK
            d,c,b,a = c,_rot(b,9),a,t1
            h,g,f,e = g,_rot(f,19),e,t2 ^ _rot(t2,9) ^ _rot(t2,17)
        v = [x ^ y for x,y in zip(v,[a,b,c,d,e,f,g,h])]
    return b''.join(x.to_bytes(4,'big') for x in v)

def double_sm3(data):
    return sm3(sm3(data))

def dy_rc4(key, data):
    data = [x & 255 for x in _units(data)] if isinstance(data,str) else list(data)
    key = bytes(key)
    if not key:
        raise ValueError('key must not be empty')
    s = list(range(255,-1,-1))
    j = 0
    for i in range(256):
        j = (j*s[i]+j+key[i % len(key)]) % 256
        s[i],s[j] = s[j],s[i]
    i = j = 0
    out = []
    for x in data:
        i = (i+1)%256
        j = (j+s[i])%256
        s[i],s[j] = s[j],s[i]
        out.append(x ^ s[(s[i]+s[j])%256])
    return bytes(out)

def custom_base64(data, table=S4):
    return base64.b64encode(bytes(data)).decode().translate(str.maketrans(STANDARD,table))

def _random_header(pair, flag, rng):
    r = int(rng()*65535)
    r1,r2 = r&255,(r>>8)&255
    if flag == 1:
        r2 = 0  # Source: Math.random * 40 (missing parentheses) -> NaN >> 0.
    elif flag == 2:
        r1 = int(rng()*240)
        if r1>109:
            r1 += r1%2 + 1
        r2 = 178  # Source: (Math.random * 255 >> 0) & 77, then OR 178.
    a,b = pair
    return [(r1&170)|(a&85),(r1&85)|(a&170),(r2&170)|(b&85),(r2&85)|(b&170)]

def _expand(data, rng):
    out=[]
    for i in range(0,len(data),3):
        if i+2>=len(data):
            out.extend(data[i:]); break
        a,b,c=data[i:i+3];x=int(rng()*1000)&255
        out.extend([(x&145)|(a&110),(x&66)|(b&189),(x&44)|(c&211),(a&145)|(b&66)|(c&44)])
    return out

@dataclass(frozen=True)
class Browser:
    inner_width: int = 1440
    inner_height: int = 900
    outer_width: int = 1440
    outer_height: int = 900
    avail_width: int = 1440
    avail_height: int = 860
    # These represent public JS screen.sizeWidth/sizeHeight, not screen.width.
    size_width: int = 1440
    size_height: int = 900
    platform: str = 'Win32'
    def text(self):
        return '|'.join(map(str,self.__dict__.values()))

def generate(query, user_agent, *, body=b'', aid=6383, page_id=7571, browser=None,
             now_ms=None, enter_ms=None, rng=None, ua_key=(0,1,14), trace=False):
    """Sign the exact encoded query and request-body bytes sent to the platform.

    The body must be the wire bytes, including UTF-8 encoding for JSON. Empty
    bodies use the same hash as GET. Test hooks permit deterministic vectors.
    """
    if not isinstance(query,str) or not isinstance(user_agent,str):
        raise TypeError('query and user_agent must be strings')
    if not isinstance(body, bytes):
        raise TypeError('body must be the exact request bytes')
    if query.startswith(('http://','https://','?')):
        raise ValueError('Pass only query text, without URL or leading ?')
    now = int(time.time()*1000) if now_ms is None else int(now_ms)
    enter = now if enter_ms is None else int(enter_ms)
    rng = random.random if rng is None else rng
    browser = Browser() if browser is None else browser
    u={}
    qhash=double_sm3(query if query.endswith('dhzx') else query+'dhzx')
    bhash=double_sm3(body+b'dhzx')
    ua_encoded=custom_base64(dy_rc4(ua_key,user_agent.strip()),S3)
    uhash=sm3(ua_encoded)
    u.update({24:41,26:int((now-1721836800000)/1000/60/60/24/14),27:6,28:(now-enter+3)&255})
    for i in range(6):u[29+i]=(now>>(8*i))&255
    u.update({35:1,36:0,38:129,39:0,40:0,41:0,42:0,43:0,44:14,45:0,46:0,47:0,
              48:qhash[9],49:qhash[18],51:qhash[3],52:bhash[10],53:bhash[19],55:bhash[4],
              56:uhash[11],57:uhash[21],59:uhash[5],66:3})
    for i in range(6):u[60+i]=((now-1)>>(8*i))&255
    for i in range(4):u[67+i]=(page_id>>(8*i))&255;u[71+i]=(aid>>(8*i))&255
    screen_units=_units(browser.text())
    time_units=_units(str((now+3)&255)+',')
    u.update({79:len(screen_units)&255,80:(len(screen_units)>>8)&255,84:len(time_units)&255,85:(len(time_units)>>8)&255})
    prefix8=_random_header([1,0],0,rng)+_random_header([1,0],2,rng)
    order=[34,44,56,61,73,29,70,45,35,49,38,66,51,68,28,48,64,47,30,71,26,55,31,69,59,40,62,63,27,72,41,74,57,52,42,39,33,67,53,43,65,46,36,24,60,32,79,80,84,85]
    fields=[u[i] for i in order]
    check=0
    for x in prefix8+fields:check^=x
    payload=fields+screen_units+time_units+[check]
    head=_random_header([3,82],1,rng)
    expanded=_expand(payload,rng)
    encrypted=dy_rc4([211],prefix8+expanded)
    raw=bytes(head)+encrypted
    result=custom_base64(raw)
    if trace:
        return {'result':result,'query_hash':list(qhash),'body_hash':list(bhash),'ua_hash':list(uhash),
                'ua_encoded':ua_encoded,'payload':payload,'expanded':expanded,'prefix8':prefix8,
                'raw_hex':raw.hex(),'chars':len(result),'raw_bytes':len(raw)}
    return result

if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser(description='Offline public-JS-compatible a_bogus port; no online validity guarantee.')
    p.add_argument('--query',required=True);p.add_argument('--ua',required=True)
    p.add_argument('--page-id',type=int,default=7571);p.add_argument('--aid',type=int,default=6383)
    a=p.parse_args()
    print(generate(a.query,a.ua,aid=a.aid,page_id=a.page_id))
