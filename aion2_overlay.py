"""
Aion 2 DPS Meter - Protocol-Native High Performance Overlay
Baseado na Engenharia Reversa do Protocolo Oficial Aion 2 (Questlog / Aletheia)
HUD inspirado no estilo oficial do Questlog com ícones de classe, Combat Power e Party Detection.
"""
import tkinter as tk
from tkinter import simpledialog
import subprocess
import threading
import queue
import time
import sys
import os
import gc
import json
import math
import struct
import ctypes
import socket
import re
import urllib.request
from functools import lru_cache
from collections import OrderedDict
import lz4.block
from PIL import Image, ImageDraw, ImageTk

if sys.platform == "win32" and sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

if sys.platform == "win32":
    class _Win32Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

TSHARK_PATH          = r"C:\Program Files\Wireshark\tshark.exe"
DEFAULT_INTERFACE    = "auto"       # Detecção automática de adaptador Npcap / IP ativo
SERVER_PORT          = 13328        # Porta de tráfego Aion 2 S2C
ENABLE_FILE_LOG      = False        # Desativado por padrão para zero I/O de disco em combate

def is_admin():
    if sys.platform != "win32":
        return True
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def check_or_request_admin():
    if sys.platform != "win32" or is_admin():
        return True
    if "--no-elevate" in sys.argv:
        return False
    try:
        if getattr(sys, "frozen", False):
            exe_path = sys.executable
            args = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe_path, args, None, 1
            )
        else:
            py_exe = sys.executable
            script = os.path.abspath(__file__)
            args = f'"{script}" ' + " ".join([f'"{arg}"' for arg in sys.argv[1:]])
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", py_exe, args, None, 1
            )
        if ret > 32:
            sys.exit(0)
    except Exception:
        pass
    return False

# Suporte a executável único (PyInstaller --onefile) e execução direta via Python
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
if getattr(sys, "frozen", False):
    BUNDLE_DIR = getattr(sys, "_MEIPASS", SCRIPT_DIR)
    BASE_DIR   = os.path.dirname(os.path.abspath(sys.executable))
else:
    BUNDLE_DIR = SCRIPT_DIR
    BASE_DIR   = SCRIPT_DIR

CONFIG_FILE          = os.path.join(BASE_DIR, "config.json")
DEBUG_LOG            = os.path.join(BASE_DIR, "meter_debug.log")
DATA_DIR             = os.path.join(BUNDLE_DIR, "data") if os.path.exists(os.path.join(BUNDLE_DIR, "data")) else os.path.join(BASE_DIR, "data")
ICONS_DIR            = os.path.join(BASE_DIR, "icons")
try:
    os.makedirs(ICONS_DIR, exist_ok=True)
except Exception:
    pass

APP_ICON_FILE        = os.path.join(BUNDLE_DIR, "app_icon.ico") if os.path.exists(os.path.join(BUNDLE_DIR, "app_icon.ico")) else os.path.join(BASE_DIR, "app_icon.ico")
QUESTLOG_SKILLS_FILE = os.path.join(DATA_DIR, "questlog_skills.json")

# ─────────────────────────────────────────────
# BANCO DE DADOS DE BOSSES E DUNGEONS (Questlog)
# ─────────────────────────────────────────────
try:
    from boss_data import is_boss, get_boss_name, BOSS_IDS, BOSS_NAMES, DUNGEON_BOSSES
except Exception:
    sys.path.insert(0, BUNDLE_DIR)
    sys.path.insert(0, BASE_DIR)
    try:
        from boss_data import is_boss, get_boss_name, BOSS_IDS, BOSS_NAMES, DUNGEON_BOSSES
    except Exception:
        BOSS_IDS = frozenset()
        BOSS_NAMES = {}
        DUNGEON_BOSSES = {}
        def is_boss(npc_id, dungeon_id=None): return False
        def get_boss_name(npc_id): return ""

_REAL_BOSS_NAMES_SET = set()
_REAL_BOSS_NAMES_LOWER = set()

def _refresh_boss_name_sets():
    global _REAL_BOSS_NAMES_SET, _REAL_BOSS_NAMES_LOWER
    _REAL_BOSS_NAMES_SET = set(v for v in BOSS_NAMES.values() if v)
    _REAL_BOSS_NAMES_LOWER = set(v.strip().lower() for v in _REAL_BOSS_NAMES_SET if v)

def is_real_boss_npc(npc_id=0, npc_name="", map_id=None):
    """Verifica se o NPC é um Boss real (ignorando objetos invisíveis/mecânicas/totens)."""
    name_check = (npc_name or (get_boss_name(npc_id) if npc_id else "") or "").strip()
    if name_check:
        low_n = name_check.lower()
        bad_tokens = (
            "invisible", "m_pd_", "n_invisible", "test_", "poison fluid",
            "thorn vines", "thorn root", "surveillance device", "hydraulic press", "sandback"
        )
        if any(bt in low_n for bt in bad_tokens):
            return False
        if low_n in _REAL_BOSS_NAMES_LOWER or name_check in _REAL_BOSS_NAMES_SET:
            return True
    if npc_id:
        if map_id and map_id in DUNGEON_BOSSES:
            if npc_id in DUNGEON_BOSSES[map_id]:
                return True
        if is_boss(npc_id, map_id):
            return True
        b_name = BOSS_NAMES.get(npc_id)
        if b_name:
            low_b = b_name.strip().lower()
            if not any(bt in low_b for bt in ("invisible", "m_pd_", "test_", "sandback")):
                return True
    return False

def _load_dynamic_game_data():
    for p in [
        os.path.join(BUNDLE_DIR, "game-data-v2.json"),
        os.path.join(BASE_DIR, "game-data-v2.json"),
        os.path.join(os.environ.get("APPDATA", ""), "Questlog", "aion-2", "game-data-v2.json")
    ]:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f).get("value", {})
                    for b in d.get("bosses", []):
                        if "npc" in b and b.get("name"):
                            BOSS_NAMES[int(b["npc"])] = b["name"]
                    for dg in d.get("dungeons", []):
                        d_id = int(dg.get("id", 0))
                        d_b = [int(x) for x in dg.get("bosses", [])]
                        if d_id and d_b:
                            DUNGEON_BOSSES[d_id] = d_b
                break
            except Exception:
                pass
    _refresh_boss_name_sets()
_load_dynamic_game_data()
QUESTLOG_NPCS_FILE   = os.path.join(DATA_DIR, "questlog_npcs.json")
ALETHEIA_DIR         = os.path.join(BUNDLE_DIR, "AION2-DPS-Meter", "data") if os.path.exists(os.path.join(BUNDLE_DIR, "AION2-DPS-Meter", "data")) else os.path.join(BASE_DIR, "AION2-DPS-Meter", "data")
SKILL_NAMES_FILE     = os.path.join(ALETHEIA_DIR, "skill_names_en.json")
NPC_NAMES_FILE       = os.path.join(ALETHEIA_DIR, "i18n", "npc_names.json")
CLASS_ICONS_DIR      = os.path.join(BUNDLE_DIR, "AION2-DPS-Meter", "assets", "classicon") if os.path.exists(os.path.join(BUNDLE_DIR, "AION2-DPS-Meter", "assets", "classicon")) else os.path.join(BASE_DIR, "AION2-DPS-Meter", "assets", "classicon")

def log(msg):
    if not ENABLE_FILE_LOG:
        return
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass

# ─────────────────────────────────────────────
# CONFIGURAÇÕES E BANCOS DE DADOS COMPACTADOS (BAIXO USO DE RAM)
# ─────────────────────────────────────────────
_CONFIG_CACHE = None
_KNOWN_CHARS_DIRTY = False
_LAST_CONFIG_SAVE = 0.0

def load_config():
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _CONFIG_CACHE = data
                    return _CONFIG_CACHE
        except Exception:
            pass
    _CONFIG_CACHE = {}
    return _CONFIG_CACHE

def save_config(cfg):
    global _CONFIG_CACHE, _KNOWN_CHARS_DIRTY
    cur = load_config()
    cur.update(cfg)
    cur.pop("local_player", None)
    _CONFIG_CACHE = cur
    _KNOWN_CHARS_DIRTY = True
    flush_config_to_disk(force=True)

def flush_config_to_disk(force=False):
    global _CONFIG_CACHE, _KNOWN_CHARS_DIRTY, _LAST_CONFIG_SAVE
    if not _KNOWN_CHARS_DIRTY or _CONFIG_CACHE is None:
        return
    now = time.time()
    if not force and (now - _LAST_CONFIG_SAVE < 30.0):
        return
    _LAST_CONFIG_SAVE = now
    _KNOWN_CHARS_DIRTY = False
    try:
        cur = dict(_CONFIG_CACHE)
        cur.pop("local_player", None)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def save_known_char(name, p_class=None, cp_val=0):
    global _CONFIG_CACHE, _KNOWN_CHARS_DIRTY
    if not name or name in ("Aguardando identificar jogador", "Você", "Aguardando Alvo"):
        return
    try:
        cur = load_config()
        known = cur.get("known_chars")
        if not isinstance(known, dict):
            known = {}
            cur["known_chars"] = known
        entry = known.get(name)
        if not isinstance(entry, dict):
            entry = {}
            known[name] = entry
        changed = False
        if p_class and entry.get("class") != p_class:
            entry["class"] = p_class
            changed = True
        if cp_val and cp_val > 0 and entry.get("combatPower") != int(cp_val):
            entry["combatPower"] = int(cp_val)
            changed = True
        if changed:
            _KNOWN_CHARS_DIRTY = True
    except Exception:
        pass

def load_json(path, default=None):
    if default is None: default = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default

def _build_compact_databases():
    skills_map = {}
    npcs_map   = {}

    raw_legacy_skills = load_json(SKILL_NAMES_FILE, {}).get("skills", {})
    for k, v in raw_legacy_skills.items():
        if v:
            skills_map[str(k)] = (str(v), None)
    del raw_legacy_skills

    raw_q_skills = load_json(QUESTLOG_SKILLS_FILE, {})
    for k, v in raw_q_skills.items():
        if isinstance(v, dict):
            skills_map[str(k)] = (v.get("name") or f"Skill #{k}", v.get("icon"))
    del raw_q_skills

    raw_legacy_npcs = load_json(NPC_NAMES_FILE, {})
    for k, v in raw_legacy_npcs.items():
        if isinstance(v, dict):
            name = v.get("en") or v.get("zh_TW") or next(iter(v.values()), None)
            if name:
                npcs_map[str(k)] = str(name)
        elif v:
            npcs_map[str(k)] = str(v)
    del raw_legacy_npcs

    raw_q_npcs = load_json(QUESTLOG_NPCS_FILE, {})
    for k, v in raw_q_npcs.items():
        if isinstance(v, dict):
            name = v.get("name") or v.get("en")
            if name:
                npcs_map[str(k)] = str(name)
        elif v:
            npcs_map[str(k)] = str(v)
    del raw_q_npcs

    gc.collect()
    return skills_map, npcs_map

COMPACT_SKILLS, COMPACT_NPCS = _build_compact_databases()

# Mapeamento Oficial de Classes do Aion 2 (Questlog zr)
CLASS_LIST = (None, "gladiator", "templar", "ranger", "assassin", "elementalist", "sorcerer", "cleric", "chanter", None, None, "fighter")

@lru_cache(maxsize=256)
def get_class_by_pcid(pcid):
    if not pcid or pcid < 1:
        return "templar"
    idx = (pcid - 1) // 4
    if 0 <= idx < len(CLASS_LIST) and CLASS_LIST[idx]:
        return CLASS_LIST[idx]
    return "gladiator"

@lru_cache(maxsize=4096)
def get_class_by_skill_id(skill_id):
    if not skill_id:
        return None
    try:
        sid = int(skill_id)
    except Exception:
        return None

    # Ataques básicos específicos de classe no banco oficial do Questlog (questlog_skills.json)
    if sid in (1001390, 1010040, 1010046):
        return "ranger"
    if sid == 1001420:
        return "gladiator"
    if sid in (1001430, 1001440) or 100011 <= sid <= 100048:
        return "elementalist"

    # IMPORTANTE (Questlog questlog_skills.json):
    # - Skills de 7 dígitos (1_000_000 .. 9_999_999, como 1200500, 1500020, 1600020, 1800000)
    #   são EXCLUSIVAMENTE skills de Monstros / NPCs / Itens / Godstones! NUNCA devem ser tratadas como classe de jogador!
    # - Skills comuns de 4 dígitos (1001..1299 Glide/Dash/Divine Power, 4001..4099 Dodge) são comuns a todas as classes!
    if 100_000 <= sid <= 9_999_999:
        return None
    if sid < 1300 or (4000 <= sid <= 4099):
        return None

    # Skills reais de classe de jogador: 8 dígitos (11_000_000 .. 19_999_999) ou base 4 dígitos (1300..1999)
    if (11_000_000 <= sid <= 19_999_999) or (1300 <= sid <= 1999):
        pfx = str(sid)[:2]
        if pfx == "11": return "gladiator"
        if pfx == "12": return "templar"
        if pfx == "13": return "assassin"
        if pfx == "14": return "ranger"
        if pfx == "15": return "sorcerer"
        if pfx == "16": return "elementalist"
        if pfx == "17": return "cleric"
        if pfx == "18": return "chanter"
        if pfx == "19": return "fighter"
    return None

class IconManager:
    def __init__(self):
        self.cache = {}
        self.downloading = set()
        self.failed = set()

    def get_skill_icon(self, icon_rel_path):
        if not icon_rel_path or icon_rel_path in self.failed:
            return None
        if icon_rel_path in self.cache:
            return self.cache[icon_rel_path]

        base_name = icon_rel_path.split("/")[-1].split(".")[0]
        local_png = os.path.join(ICONS_DIR, f"{base_name}.png")
        local_webp = os.path.join(ICONS_DIR, f"{base_name}.webp")

        # ImageTk.PhotoImage SEMPRE instanciado exclusivamente na Main Thread (Thread-Safe!)
        if os.path.exists(local_png):
            try:
                with Image.open(local_png) as img:
                    clean_img = _composite_for_colorkey(img.convert("RGBA"), _get_theme_bg_rgb("skill"), alpha_cutoff=75)
                    photo = ImageTk.PhotoImage(clean_img)
                self.cache[icon_rel_path] = photo
                return photo
            except Exception:
                pass
        elif os.path.exists(local_webp):
            try:
                with Image.open(local_webp) as raw_im:
                    img = raw_im.convert("RGBA").resize((20, 20), Image.Resampling.LANCZOS)
                    img.save(local_png)
                    clean_img = _composite_for_colorkey(img, _get_theme_bg_rgb("skill"), alpha_cutoff=75)
                    photo = ImageTk.PhotoImage(clean_img)
                self.cache[icon_rel_path] = photo
                return photo
            except Exception:
                pass

        if icon_rel_path not in self.downloading:
            self.downloading.add(icon_rel_path)
            threading.Thread(target=self._download, args=(icon_rel_path, local_webp, local_png), daemon=True).start()

        return None

    def _download(self, icon_rel_path, local_webp, local_png):
        # Thread secundária apenas baixa e salva o PNG no disco (sem tocar no Tcl/Tk!)
        try:
            clean = icon_rel_path
            if "." in clean:
                clean = clean[:clean.rfind(".")]
            url = f"https://cdn.questlog.gg/aion-2{clean}.webp"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
            with open(local_webp, "wb") as f:
                f.write(data)
            with Image.open(local_webp) as raw_im:
                img = raw_im.convert("RGBA").resize((20, 20), Image.Resampling.LANCZOS)
                img.save(local_png)
        except Exception:
            self.failed.add(icon_rel_path)
        finally:
            self.downloading.discard(icon_rel_path)

ICON_MGR = IconManager()

@lru_cache(maxsize=512)
def get_skill_info(skill_id):
    if not skill_id:
        return "Ataque Básico", None

    for cand in (skill_id, (skill_id // 10) * 10, (skill_id // 10000) * 10000, skill_id // 10000):
        entry = COMPACT_SKILLS.get(str(cand))
        if entry:
            return entry

    return f"Skill #{skill_id}", None

@lru_cache(maxsize=512)
def get_npc_name_by_id(npc_id):
    if not npc_id:
        return None
    for key in (str(npc_id), str(npc_id % 10_000_000)):
        name = COMPACT_NPCS.get(key)
        if name:
            return name
    return None

# ─────────────────────────────────────────────
# LEITOR DE BYTES PROTOCOLAR (ByteReader)
# ─────────────────────────────────────────────
class ByteReader:
    def __init__(self, data, offset=0, end=None):
        self.data   = data
        self.pos    = offset
        self.end    = len(data) if end is None else end
        self.bit_at = -1
        self.bit    = 0

    def remaining(self):
        return self.end - self.pos

    def u8(self):
        if self.pos >= self.end: return 0
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u16(self):
        if self.pos + 2 > self.end: return 0
        v = struct.unpack_from('<H', self.data, self.pos)[0]
        self.pos += 2
        return v

    def u32(self):
        if self.pos + 4 > self.end: return 0
        v = struct.unpack_from('<I', self.data, self.pos)[0]
        self.pos += 4
        return v

    def i32(self):
        if self.pos + 4 > self.end: return 0
        v = struct.unpack_from('<i', self.data, self.pos)[0]
        self.pos += 4
        return v

    def f32(self):
        if self.pos + 4 > self.end: return 0.0
        v = struct.unpack_from('<f', self.data, self.pos)[0]
        self.pos += 4
        return v

    def i64(self):
        if self.pos + 8 > self.end: return 0
        v = struct.unpack_from('<q', self.data, self.pos)[0]
        self.pos += 8
        return v

    def v32(self):
        result = 0
        shift  = 0
        while self.pos < self.end:
            b = self.data[self.pos]
            self.pos += 1
            result |= (b & 0x7F) << shift
            if not (b & 0x80): break
            shift += 7
        return result & 0xFFFFFFFF

    def vi32(self):
        v = self.v32()
        if v >= 0x80000000:
            return v - 0x100000000
        return v

    def vi64(self):
        result = 0
        shift  = 0
        while self.pos < self.end:
            b = self.data[self.pos]
            self.pos += 1
            result |= (b & 0x7F) << shift
            if not (b & 0x80): break
            shift += 7
        if result >= 0x8000000000000000:
            return result - 0x10000000000000000
        return result

    def str(self):
        length = self.v32()
        if length <= 0 or self.pos + length > self.end:
            return ""
        s = self.data[self.pos : self.pos + length]
        self.pos += length
        if s and s[-1] == 0:
            s = s[:-1]
        return s.decode('utf-8', errors='ignore').strip()

    def bool(self):
        if self.bit_at < 0:
            if self.pos >= self.end: return False
            self.bit_at = self.pos
            self.bit    = 0
            self.pos   += 1
        b_val = bool(self.data[self.bit_at] & (1 << self.bit))
        self.bit += 1
        if self.bit > 7:
            self.bit_at = -1
            self.bit    = 0
        return b_val

    def list(self, item_fn):
        count = self.v32()
        if count > 5000 or self.pos >= self.end:
            return []
        items = []
        for _ in range(count):
            if self.pos >= self.end: break
            items.append(item_fn(self))
        return items

    def optional(self, flag, fn):
        if flag:
            return fn(self)
        return None

# ─────────────────────────────────────────────
# DECODIFICADORES OFICIAIS DE ESTRUTURAS
# ─────────────────────────────────────────────
def decode_varint(data, offset, end):
    result = 0
    shift  = 0
    cur    = offset
    while cur < end:
        b = data[cur]
        cur += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, cur - offset
        shift += 7
    return None

def get_packet_length(data, offset, end):
    if end - offset < 3: return None
    res = decode_varint(data, offset, end)
    if not res: return None
    val, vlen = res
    n = 4 - vlen
    if n < 0 or val < n: return -1, 0
    o = val - n
    if o < vlen + 2 or o > 65536: return -1, 0
    return o, vlen

def read_pos(r):
    return {'x': r.f32(), 'y': r.f32(), 'z': r.f32()}

def read_desc(r):
    t = r.u8()
    nick = r.str() if (t & 1) else ""
    pcId = r.i32()
    race = r.u8() if (t & 2) else 0
    gender = r.u8() if (t & 4) else 0
    if t & 8:
        r.u8()
        r.i32()
    overrideRace = r.u8() if (t & 16) else 0
    return {'nickname': nick, 'pcId': pcId, 'race': race, 'gender': gender}

def read_state(r):
    t = r.u16()
    pos = read_pos(r)
    dir_ = r.f32()
    moveDir = r.u16()
    if t & 1: read_pos(r)
    if t & 2: r.f32()
    if t & 4: r.u16()
    if t & 8: read_pos(r)
    if t & 16: read_pos(r)
    targetKey = r.i32() if (t & 32) else 0
    live = r.u8()
    hp = r.vi64()
    hpMax = r.vi64()
    mp = r.i32()
    r.i32()  # mpMax
    r.i32()  # ap
    r.i32()  # apMax
    r.i32()  # sp
    r.i32()  # spMax
    r.i32()  # dp
    r.i32()  # dpMax
    r.i32()  # dpStep
    r.i32()  # op
    r.i32()  # opMax
    r.i32()  # fp
    r.i32()  # fpMax
    if t & 64: r.u8()
    if t & 128: r.i32()
    if t & 256: r.u8()
    if t & 512: r.u8()
    if t & 1024: r.vi32()
    if t & 2048: r.i32()
    if t & 4096: r.i32()
    if t & 8192: r.u8()
    if t & 16384: r.i32()
    if t & 32768: r.i32()
    return {'pos': pos, 'targetKey': targetKey, 'live': live, 'hp': hp, 'hpMax': hpMax}

def read_deco_slot(r):
    r.u8(); r.u8(); r.u8(); r.u8(); r.bool()  # slot, colorR, colorG, colorB, colorRemove
    r.i32(); r.i32()                          # materialId, patternId
    r.u8(); r.u8(); r.u8(); r.bool()          # patternColorR, patternColorG, patternColorB, patternColorRemove
    for _ in range(4): r.u16()
    r.u8(); r.bool()
    r.u16(); r.u16()

def read_equip(r):
    r.i32(); r.u8(); r.u8(); r.i64(); r.bool(); r.i32()
    r.list(read_deco_slot)
    r.list(lambda x: x.i32())
    r.bool(); r.bool(); r.bool(); r.vi32()

def read_mappin(r):
    t = r.u8()
    r.u8(); r.str(); r.i32(); read_pos(r); r.i64(); r.i64()
    if t & 1: r.list(lambda x: x.i64())

def read_plotter(r):
    shield_block = r.bool()
    weapon_block = r.bool()
    perfect      = r.bool()
    hardhit      = r.bool()
    ironwall     = r.bool()
    restoration  = r.bool()
    restoration_hp = r.vi64()
    perfect_block = r.bool()
    attack_angle = r.u8()
    return {
        'isShieldblock': shield_block,
        'isWeaponblock': weapon_block,
        'isPerfect':     perfect,
        'isHardhit':     hardhit,
        'isIronwall':    ironwall,
        'isPerfectBlock': perfect_block
    }

def read_abnormal(r):
    t = r.u8()
    r.vi32()  # uid
    r.i32()   # abnormalId
    r.i64()   # durationMs
    r.i64()   # expireTime
    if t & 1: r.vi32()  # casterKey
    r.u8()    # abnormalLevel
    if t & 2: r.i32()   # skillId
    r.bool()  # readyToRemove
    if t & 4: r.vi32()  # multiplyCasterKey
    if t & 8: r.i32()   # multiplyValue
    if t & 16: read_pos(r)  # rangeBase

# Conjunto O(1) de opcodes monitorados para descarte imediato de pacotes irrelevantes (~85% do tráfego)
HANDLED_OPCODES = frozenset({
    13824, 13845, 13857, 13875, 13889, 13890, 13893, 13910,
    14340, 14341, 14388, 14389,
    22318,
    36096, 36100, 36129,
    37376, 37389, 37395, 37401, 37403, 37404, 37407, 37408, 37410, 37663,
    38402, 38410, 38426, 38427, 38434, 38443, 38444, 38446,
    38658, 38667
})

# ─────────────────────────────────────────────
# PARSER E DESPACHANTE DE STREAM
# ─────────────────────────────────────────────
class PacketDispatcher:
    def __init__(self, event_queue):
        self.event_queue       = event_queue
        self.buffer            = bytearray()
        self.is_synced         = False
        self.streams           = OrderedDict()  # stream_id -> {"buf": bytearray, "synced": bool}
        self.current_party_key = 0
        self.current_map_id    = None

    def push(self, data_chunk, stream_id=None):
        if not data_chunk:
            return
        if stream_id is None:
            self.buffer.extend(data_chunk)
            self.process_buffer()
            return
        st = self.streams.get(stream_id)
        if st is None:
            if len(self.streams) >= 32:
                self.streams.popitem(last=False)
            st = {"buf": bytearray(), "synced": False}
            self.streams[stream_id] = st
        else:
            self.streams.move_to_end(stream_id)
        st["buf"].extend(data_chunk)
        st["synced"] = self._process_buf(st["buf"], st["synced"])
        self.is_synced = st["synced"]

    def process_buffer(self):
        self.is_synced = self._process_buf(self.buffer, self.is_synced)

    def _process_buf(self, buf, synced):
        pos = 0
        buf_len = len(buf)

        while pos < buf_len:
            res = get_packet_length(buf, pos, buf_len)
            if res is None:
                break
            pkt_len, vlen = res
            if pkt_len < 0:
                synced = False
                pos += 1
                continue
            if pos + pkt_len > buf_len:
                break

            body_start = pos + vlen + 2
            body_end   = pos + pkt_len

            opcode = buf[pos + vlen] | (buf[pos + vlen + 1] << 8)

            if opcode == 65535:  # 0xFFFF = LZ4 Bundle
                if body_end - body_start > 4:
                    decomp_size = struct.unpack_from('<I', buf, body_start)[0]
                    if 0 < decomp_size <= 262144:
                        try:
                            decomp = lz4.block.decompress(
                                memoryview(buf)[body_start + 4 : body_end],
                                uncompressed_size=decomp_size
                            )
                            self.is_synced = synced
                            self.parse_payload_packets(decomp)
                            synced = True
                        except Exception:
                            pass
                pos += pkt_len
                continue
            elif opcode in HANDLED_OPCODES:
                self.is_synced = synced
                self.dispatch_packet(opcode, buf, body_start, body_end, from_lz4=False)

            pos += pkt_len

        if pos > 0:
            del buf[:pos]
        return synced

    def parse_payload_packets(self, payload):
        pos = 0
        p_len = len(payload)
        while pos < p_len:
            res = get_packet_length(payload, pos, p_len)
            if res is None:
                break
            pkt_len, vlen = res
            if pkt_len <= 0 or pos + pkt_len > p_len:
                break
            body_start = pos + vlen + 2
            body_end   = pos + pkt_len
            opcode = payload[pos + vlen] | (payload[pos + vlen + 1] << 8)
            if opcode in HANDLED_OPCODES:
                self.dispatch_packet(opcode, payload, body_start, body_end, from_lz4=True)
            pos += pkt_len
        return True

    def dispatch_packet(self, opcode, buf, start, end, from_lz4=False):
        if opcode not in HANDLED_OPCODES:
            return
        try:
            reader = ByteReader(buf, start, end)

            # 0. MapFrame_NT (13824): Sincronização de Relógio do Servidor (para Enrage/Berserk Timer)
            if opcode == 13824:
                if end - start == 8:
                    srv_time = reader.i64()
                    if srv_time > 1700000000000:
                        self.event_queue.put({
                            "type":        "server_time",
                            "server_time": int(srv_time),
                            "local_ms":    int(time.time() * 1000)
                        })

            # 0.2. Login_RS (13845): Lista de Personagens na Conta ao Conectar (Idêntico ao $4 / x4 do Questlog)
            elif opcode == 13845:
                try:
                    res = reader.u16()
                    if res == 0:
                        reader.i64(); reader.i64()  # serverNow, serverNowLocal
                        chars_list = []
                        cnt = reader.v32()
                        for _ in range(cnt):
                            k = reader.i32()
                            n = reader.str()
                            pid = reader.i32()
                            reader.u8(); reader.u8()  # race, gender
                            reader.i32(); reader.i32(); reader.i32()  # level, conquerorLevel, equipItemLevel
                            c_dbid = 0
                            c_cp = 0
                            try:
                                reader.i64(); reader.i32(); reader.i64()  # exp, combatLevel, combatExp
                                reader.str(); reader.i64()  # guildName, logoutTime
                                read_pos(reader); reader.i32(); reader.i64(); reader.i64()  # pos, zoneId, regTime, pendingDeleteTime
                                reader.list(read_equip)  # lobbyEquips
                                c_dbid = int(reader.i64())
                                reader.i32(); reader.i64(); reader.i32(); reader.i32()  # blockReasonNo, blockEndTime, wingId, wingSkinId
                                reader.list(lambda r: r.u8())  # customizingData
                                reader.u8(); reader.bool()  # voiceType, preGenerated
                                reader.list(lambda r: (r.i32(), r.i64(), r.bool(), r.i64()))  # itemCountList (S4)
                                reader.i64(); reader.u8()  # lastNicknameChangeTime, slotNo
                                c_cp = int(reader.i64())
                            except Exception:
                                pass
                            cls = get_class_by_pcid(pid)
                            if n and not n.startswith("$"):
                                chars_list.append({
                                    "key":         k,
                                    "dbid":        c_dbid,
                                    "name":        n,
                                    "pcId":        pid,
                                    "class":       cls,
                                    "combatPower": c_cp if c_cp > 0 else 0
                                })
                        if chars_list:
                            self.event_queue.put({
                                "type": "login_characters",
                                "characters": chars_list
                            })
                except Exception:
                    pass

            # 0.5. PrepareEnterMap_NT (13857): Troca de Mapa / Entrada em Dungeon / Loading (Idêntico ao PrepareEnterMap_NT do Questlog)
            elif opcode == 13857:
                reader.i32()
                map_id = reader.i32()
                reader.i64()
                read_pos(reader)
                reader.f32()
                reason = reader.u8()
                reader.u8()
                reader.i64()
                reader.list(lambda r: (r.i32(), r.u8(), r.i64()))
                tp_effect = reader.vi32()
                cutscene = reader.str()
                inform_type = reader.u8()
                if map_id > 0:
                    log(f"PrepareEnterMap_NT: mapId={map_id}, reason={reason}, tpEffect={tp_effect}, cutscene='{cutscene}', inform={inform_type}")
                    self.current_map_id = map_id
                    self.event_queue.put({
                        "type":            "map_change",
                        "map_id":          map_id,
                        "reason":          reason,
                        "teleport_effect": tp_effect,
                        "cutscene":        cutscene,
                        "inform_type":     inform_type
                    })

            # 1. MyCharAppear_NT (13875): Próprio Jogador (Idêntico ao A4 do Questlog)
            elif opcode == 13875:
                char_key = reader.vi32()
                flags = reader.u32()
                t = reader.u8()
                nick = reader.str() if (t & 1) else ""
                serverId = reader.u16()
                pcId = reader.i32()
                p_class = get_class_by_pcid(pcId)
                local_dbid = 0
                cp_val = 0
                appear_reason = 0
                map_key = 0
                appear_map_id = 0
                try:
                    if t & 2: reader.u8()
                    reader.i32(); reader.i32(); reader.i32(); reader.i32()
                    reader.i64(); reader.i32(); reader.i64()
                    if t & 4: reader.u8()
                    reader.list(lambda r: (r.u16(), r.i64(), r.u16(), r.u16()))
                    reader.list(lambda r: (r.u8(), r.u16(), r.i64(), r.u16()))
                    reader.i32(); reader.i32(); reader.i64(); reader.u8()
                    if t & 8: reader.u8()
                    if t & 16: reader.list(lambda r: (r.u8(), r.u16()))
                    if t & 32: reader.list(lambda r: (r.u8(), r.u16()))
                    read_state(reader)
                    if flags & 1:
                        reader.i64(); reader.str(); reader.u16(); reader.u8(); reader.i32(); reader.i64(); reader.u16(); reader.str()
                    reader.list(lambda r: (r.u16(), r.i32()))
                    reader.list(read_abnormal)
                    reader.list(read_equip)
                    if flags & 2: appear_reason = int(reader.u8())
                    map_key = int(reader.i64())
                    appear_map_id = int(reader.i32())
                    if flags & 4: reader.i32()
                    if flags & 8: reader.i32()
                    if flags & 16: read_pos(reader)
                    if flags & 32: reader.u16()
                    local_dbid = int(reader.i64())
                    if flags & 64: reader.f32()
                    if flags & 128: reader.i32()
                    if flags & 256: reader.u8()
                    if flags & 512: reader.u8()
                    if flags & 1024: reader.u8()
                    if flags & 2048: reader.bool()
                    if flags & 4096: reader.vi32()
                    reader.list(lambda r: r.u8())
                    reader.bool()
                    if flags & 8192: reader.u8()
                    if flags & 16384: reader.vi32()
                    if flags & 32768: reader.i32()
                    if flags & 65536: reader.i64()
                    if flags & 131072: reader.list(read_mappin)
                    if flags & 262144: reader.i32()
                    if flags & 524288: reader.i32()
                    if flags & 1048576: reader.i32()
                    if flags & 2097152: reader.i64()
                    if flags & 4194304:
                        reader.i64(); reader.u16(); reader.str(); reader.i32(); reader.u8()
                    if flags & 8388608: reader.u16()
                    reader.i32(); reader.i32(); reader.i64()
                    if flags & 16777216: reader.bool()
                    if flags & 33554432: reader.i64()
                    if flags & 67108864: reader.i32()
                    if flags & 134217728:
                        reader.i32(); reader.i32(); reader.i32(); reader.i32()
                    cp_val = int(reader.i64())
                except Exception:
                    cp_val = 0

                # Fallback no tail do pacote caso cp_val tenha falhado (busca par combatPower <= highestCombatPower)
                if not (100 <= cp_val <= 10_000_000) and end - start > 64:
                    cp_val = 0
                    scan_start = max(start + 32, end - 140)
                    for off in range(end - 18, scan_start, -1):
                        c1, c2 = struct.unpack_from('<qq', buf, off)
                        if 1000 <= c1 <= c2 <= 5_000_000 and (c2 - c1) <= c1:
                            cp_val = int(c1)
                            break

                if appear_map_id > 0:
                    self.current_map_id = appear_map_id

                if char_key:
                    log(f"MyCharAppear_NT: Key={char_key}, DBID={local_dbid}, Nick='{nick}', pcId={pcId}, Class={p_class}, CP={cp_val}, mapId={appear_map_id}, mapKey={map_key}, reason={appear_reason}")
                    self.event_queue.put({
                        "type":        "my_char",
                        "key":         char_key,
                        "dbid":        local_dbid if local_dbid > 0 else 0,
                        "name":        nick,
                        "pcId":        pcId,
                        "class":       p_class,
                        "combatPower": cp_val,
                        "map_id":      appear_map_id if appear_map_id > 0 else 0,
                        "map_key":     map_key,
                        "reason":      appear_reason
                    })

            # 2. CharAppear_NT (13893): Outros Jogadores (Idêntico ao w4 do Questlog: extrai dbid + combatPower)
            elif opcode == 13893:
                char_key = reader.vi32()
                flags    = reader.u32()
                desc     = read_desc(reader)
                pc_id    = desc.get('pcId', 0)
                if 1 <= pc_id <= 60:
                    p_class  = get_class_by_pcid(pc_id)
                    dbid_val = 0
                    cp_val   = 0
                    try:
                        read_state(reader)
                        if flags & 1: reader.u16()
                        if flags & 2:
                            reader.i64(); reader.str(); reader.u16(); reader.u8(); reader.i32(); reader.i64(); reader.u16(); reader.str()
                        reader.list(read_abnormal)
                        reader.list(read_equip)
                        if flags & 4: reader.u8()
                        if flags & 8: reader.u8()
                        if flags & 16: reader.bool()
                        if flags & 32: reader.bool()
                        if flags & 64: reader.u8()
                        if flags & 128: read_pos(reader)
                        if flags & 256: reader.i64()
                        if flags & 512: reader.u16()
                        if flags & 1024: reader.u16()
                        if flags & 2048: reader.i64()
                        if flags & 4096: reader.bool()
                        if flags & 8192: reader.u8()
                        if flags & 16384: reader.bool()
                        dbid_val = int(reader.i64())
                        reader.list(lambda r: (r.u16(), r.i32()))  # stats
                        reader.i32(); reader.i32(); reader.i32()   # level, conquerorLevel, equipItemLevel
                        if flags & 32768: reader.i32()
                        if flags & 65536: reader.i32()
                        if flags & 131072: reader.i32()
                        reader.list(lambda r: r.u8())              # customizingData
                        if flags & 262144: reader.u8()
                        if flags & 524288: reader.i32()
                        if flags & 1048576:
                            st = reader.u8()
                            reader.u8(); reader.i32(); reader.u8(); reader.u8(); reader.bool(); reader.i32()
                            if st & 1: reader.i64()
                            if st & 2: reader.i32()
                            if st & 4: reader.i64()
                            if st & 8: reader.i32()
                        if flags & 2097152: reader.i32()
                        if flags & 4194304: reader.i32()
                        if flags & 8388608: reader.i32()
                        if flags & 16777216: reader.i32()
                        if flags & 33554432: reader.bool()
                        if flags & 67108864: reader.i32()
                        cp_val = int(reader.i64())
                    except Exception:
                        pass

                    if not (1000 <= cp_val <= 10_000_000) and end - start >= 32:
                        cp_val = 0
                        try:
                            raw_cp = struct.unpack_from('<q', buf, end - 10)[0]
                            if 10_000 <= raw_cp <= 10_000_000:
                                cp_val = int(raw_cp)
                        except Exception:
                            pass
                        if cp_val == 0:
                            scan_limit = max(start + 16, end - 36)
                            for off in range(end - 8, scan_limit, -1):
                                try:
                                    cand = struct.unpack_from('<q', buf, off)[0]
                                    if 10_000 <= cand <= 5_000_000:
                                        cp_val = int(cand)
                                        break
                                except Exception:
                                    pass

                    if desc['nickname'] or dbid_val > 0:
                        log(f"CharAppear_NT: Key={char_key}, DBID={dbid_val}, Nick='{desc['nickname']}', Class={p_class}, CP={cp_val}")
                        self.event_queue.put({
                            "type":        "other_char",
                            "key":         char_key,
                            "dbid":        dbid_val if dbid_val > 0 else 0,
                            "name":        desc['nickname'] or "",
                            "pcId":        pc_id,
                            "class":       p_class,
                            "combatPower": cp_val
                        })

            # 3. CharCombatPowerUpdate_NT (13910): Combat Power do Jogador Local (Sempre 16 bytes: combatPower i64 + highestCombatPower i64)
            elif opcode == 13910:
                if end - start == 16:
                    cp = reader.i64()
                    highest_cp = reader.i64()
                    if 100 <= cp <= highest_cp <= 10_000_000:
                        log(f"CharCombatPowerUpdate_NT: CP={cp} (Max={highest_cp})")
                        self.event_queue.put({"type": "local_cp", "combatPower": int(cp)})

            # 4. NpcAppear_NT (13889): Monstro ou Summon/Totem Spawna com HP Máximo (+ Enrage Timer e parentKey)
            elif opcode == 13889:
                npc_key = reader.vi32()
                flags   = reader.u16()
                desc    = read_desc(reader)
                state   = read_state(reader)
                parent_key = 0
                try:
                    reader.list(read_abnormal)
                    if flags & 1: reader.u8()
                    if flags & 2: reader.u8()
                    if flags & 4: reader.u8()
                    if flags & 8: reader.bool()
                    if flags & 16: parent_key = reader.i32()
                except Exception:
                    parent_key = 0

                berserk_ms = 0
                if flags & 16384:
                    tail_offset = end - (12 if (flags & 32768) else 8)
                    if tail_offset >= start:
                        berserk_ms = struct.unpack_from('<q', buf, tail_offset)[0]
                npc_id = desc['pcId']
                npc_name = get_boss_name(npc_id) or get_npc_name_by_id(npc_id) or f"Monstro #{npc_id}"
                is_b = is_real_boss_npc(npc_id, npc_name, self.current_map_id)
                self.event_queue.put({
                    "type":       "npc_spawn",
                    "key":        npc_key,
                    "npc_id":     npc_id,
                    "name":       npc_name,
                    "is_boss":    is_b,
                    "hp":         state['hp'],
                    "hp_max":     state['hpMax'],
                    "parent_key": int(parent_key) if parent_key > 0 else 0,
                    "berserk_ms": int(berserk_ms) if berserk_ms > 0 else 0
                })

            # 4.5. CombatStateUpdate_NT (36129): Estado de Combate + Boss Enrage/Berserk Timestamp Oficial
            elif opcode == 36129:
                entity_key   = reader.vi32()
                flags        = reader.u8()
                combat_state = reader.u8()
                berserk_ms   = reader.i64() if (flags & 1) else 0
                self.event_queue.put({
                    "type":       "combat_state",
                    "key":        entity_key,
                    "in_combat":  (combat_state != 0),
                    "berserk_ms": int(berserk_ms) if berserk_ms > 0 else 0
                })

            # 4.8. CharPointUpdate_NT (36096): Atualização oficial de HP / MaxHP do Servidor (Questlog XA)
            elif opcode == 36096:
                entity_key = reader.vi32()
                flags      = reader.u8()
                hp_val     = None
                hp_max_val = None
                if flags & 1:
                    cnt = reader.v32()
                    for _ in range(cnt):
                        pt_type = reader.u8()
                        pt_val  = reader.i32()
                        if pt_type == 0: hp_val = int(pt_val)
                        elif pt_type == 7: hp_max_val = int(pt_val)
                if flags & 2:
                    cnt = reader.v32()
                    for _ in range(cnt):
                        pt_type = reader.u8()
                        pt_val  = reader.i64()
                        if pt_type == 0: hp_val = int(pt_val)
                        elif pt_type == 7: hp_max_val = int(pt_val)
                if hp_val is not None or hp_max_val is not None:
                    self.event_queue.put({
                        "type":   "hp_update",
                        "key":    entity_key,
                        "hp":     hp_val,
                        "hp_max": hp_max_val
                    })

            # 5. SetMainTarget_RS (14388) & TargetUpdate_NT (14389): Alvo Selecionado
            elif opcode in (14388, 14389):
                if opcode == 14388:
                    reader.u8()
                    res = reader.u16()
                    target_key = reader.vi32()
                    if res == 0 and target_key > 0:
                        self.event_queue.put({"type": "target_change", "target_key": target_key, "caster_key": None})
                else:
                    entity_key = reader.vi32()
                    reader.u8()
                    target_key = reader.vi32()
                    if target_key > 0:
                        self.event_queue.put({"type": "target_change", "target_key": target_key, "caster_key": entity_key})

            # 5.2. PartySetTargetByBoss_NT (37408) & PartyDungeonRewardMiddleBossKill_NT (22318)
            elif opcode == 37408:
                if (from_lz4 or self.is_synced) and (end - start) <= 6:
                    target_key = reader.vi32()
                    if target_key > 0:
                        self.event_queue.put({"type": "boss_target", "target_key": target_key})
            elif opcode == 22318:
                if (from_lz4 or self.is_synced) and (end - start) == 4:
                    npc_id = reader.i32()
                    if npc_id > 0:
                        self.event_queue.put({"type": "dungeon_boss_killed", "npc_id": npc_id})

            # 6. SkillEffect_NT (14340): Dano Principal (Idêntico ao BT(e,t) do Questlog)
            elif opcode == 14340:
                target_key = reader.vi32()
                flags      = reader.u16()
                caster_key = reader.vi32()
                skill_id   = reader.i32()
                reader.u8()
                if flags & 1: reader.i32()
                hit_type = reader.u8()
                plotter  = read_plotter(reader) if (flags & 2) else None
                effect_id = reader.i32()
                reader.i32(); reader.vi32()
                dmg = reader.vi64() if (flags & 4) else 0
                if flags & 8: reader.i32()
                if flags & 16: reader.bool()
                extra_hits = reader.list(lambda r: r.vi64()) if (flags & 32) else []
                # No Questlog (BT): r = Number(t.dmg) já contém a soma dos hits; critical é estritamente hitType == 3
                total_dmg  = int(dmg)
                is_crit    = (hit_type == 3)

                if total_dmg > 0:
                    self.event_queue.put({
                        "type":       "damage",
                        "caster_key": caster_key,
                        "target_key": target_key,
                        "skill_id":   skill_id,
                        "damage":     total_dmg,
                        "is_crit":    is_crit,
                        "over_time":  False,
                        "time":       time.time()
                    })

            # 7. SkillEffectByAbnormal_NT (14341): DoT (Idêntico ao jA(e) / VT(e,t,r) do Questlog)
            elif opcode == 14341:
                target_key = reader.vi32()
                flags      = reader.u8()
                caster_key = reader.vi32()
                abnormal_uid = reader.vi32()
                effect_id  = reader.i32()
                if flags & 1: reader.vi64()  # remainDmg
                dot_dmg = reader.vi64() if (flags & 2) else 0
                if flags & 4: reader.list(lambda r: r.i32())  # barrierIdList (essencial p/ não deslocar skillId!)
                skill_id = reader.i32() if (flags & 8) else 0
                if flags & 16: reader.vi32()  # blockedSkillCasterKeyByImmune
                if flags & 32: reader.i32()   # blockedSkillIdByImmune
                refl_skill_id = reader.i32() if (flags & 64) else 0

                if dot_dmg > 0:
                    self.event_queue.put({
                        "type":       "damage",
                        "caster_key": caster_key,
                        "target_key": target_key,
                        "skill_id":   refl_skill_id if refl_skill_id > 0 else skill_id,
                        "damage":     int(dot_dmg),
                        "is_crit":    False,
                        "over_time":  True,
                        "time":       time.time()
                    })

            # 8. CharDie_NT (36100): Morte Oficial
            elif opcode == 36100:
                dead_key   = reader.vi32()
                skill_id   = reader.i32()
                caster_key = reader.vi32()
                reader.u16()
                killer_nick = reader.str()
                self.event_queue.put({
                    "type":        "death",
                    "dead_key":    dead_key,
                    "killer_key":  caster_key,
                    "killer_nick": killer_nick,
                    "is_despawn":  False
                })

            # 9. NpcDisappear_NT (13890): Despawn
            elif opcode == 13890:
                dead_key = reader.vi32()
                self.event_queue.put({
                    "type":        "death",
                    "dead_key":    dead_key,
                    "killer_key":  0,
                    "killer_nick": "",
                    "is_despawn":  True
                })

            # 10. PartyInfo_NT (37376): Lista de Membros do Grupo
            elif opcode == 37376:
                t = reader.u8()
                party_key = reader.i64()
                leader_dbid = reader.i64()
                limit_member = reader.i32()
                distribution_type = reader.u8()
                special_dist_type = reader.u8()
                special_dist_grade = reader.u8()
                join_type = reader.u8()
                if t & 1:
                    t_ft = reader.u8()
                    reader.i32()
                    if t_ft & 1: reader.i32()
                    reader.i32()
                if t & 2:
                    cnt = reader.v32()
                    for _ in range(cnt):
                        tm = reader.u8()
                        reader.u8(); reader.i32(); reader.str()
                        if tm & 1: reader.i32()
                if t & 4:
                    cnt = reader.v32()
                    for _ in range(cnt):
                        reader.u8(); reader.i32(); read_pos(reader); reader.bool()
                if t & 8:
                    cnt = reader.v32()
                    for _ in range(cnt):
                        reader.u8(); reader.vi32(); reader.str(); reader.i32(); reader.str(); reader.i64(); reader.i32(); reader.i32()

                members_count = reader.v32()
                members = []
                for _ in range(members_count):
                    m_t = reader.u8()
                    m_num = reader.u8()
                    m_key = reader.i32()
                    m_born_server = reader.u16()
                    m_cur_server = reader.u16()
                    m_acc_id = reader.str()
                    m_dbid = reader.i64()
                    m_nick = reader.str()
                    m_pcid = reader.i32()
                    reader.vi64(); reader.vi64()
                    reader.i32(); reader.i32()
                    reader.i32(); reader.i32()
                    reader.i32(); reader.i32()
                    reader.i64(); reader.i32()
                    read_pos(reader)
                    reader.bool()
                    if m_t & 1: reader.str()
                    if m_t & 2: reader.i32()
                    m_lvl = reader.i32()
                    reader.i32(); reader.i32()
                    reader.bool(); reader.bool()
                    if m_t & 4:
                        rb_cnt = reader.v32()
                        for _ in range(rb_cnt):
                            rb_t = reader.u8()
                            reader.i32(); reader.u8()
                            if rb_t & 1: reader.vi32()
                    m_cp = reader.i64()
                    reader.u8()
                    if m_nick and 1 <= m_pcid <= 60 and m_cp >= 0:
                        members.append({
                            "key":         m_key,
                            "dbid":        m_dbid,
                            "name":        m_nick,
                            "pcId":        m_pcid,
                            "class":       get_class_by_pcid(m_pcid),
                            "combatPower": int(m_cp)
                        })
                if members:
                    if party_key > 0:
                        self.current_party_key = party_key
                    log(f"PartyInfo_NT: {len(members)} membros")
                    self.event_queue.put({"type": "party_info", "members": members})

            # 10.5. ForceInfo_NT (38402): Lista de Membros de Aliança/Force em Dungeons
            elif opcode == 38402:
                t = reader.u8()
                force_key = reader.i64()
                reader.i64()
                reader.list(lambda r: r.i64())
                reader.i32(); reader.u8(); reader.u8(); reader.u8()
                if t & 1:
                    cnt = reader.v32()
                    for _ in range(cnt):
                        tm = reader.u8(); reader.u8(); reader.i32(); reader.str()
                        if tm & 1: reader.i32()
                if t & 2:
                    cnt = reader.v32()
                    for _ in range(cnt):
                        reader.u8(); reader.i32(); read_pos(reader); reader.bool()
                parties_cnt = reader.v32()
                members = []
                for _ in range(parties_cnt):
                    reader.i64(); reader.u8(); reader.i32()
                    m_cnt = reader.v32()
                    for _ in range(m_cnt):
                        m_t = reader.u8()
                        reader.u8()
                        m_key = reader.i32()
                        reader.u16(); reader.u16(); reader.str()
                        m_dbid = reader.i64()
                        m_nick = reader.str()
                        m_pcid = reader.i32()
                        reader.vi64(); reader.vi64(); reader.i64(); reader.i32()
                        reader.bool()
                        if m_t & 1: reader.str()
                        if m_t & 2: reader.i32()
                        reader.i32(); reader.i32()
                        reader.bool()
                        reader.i32()
                        read_pos(reader)
                        m_cp = reader.i64()
                        reader.u8()
                        if m_nick and 1 <= m_pcid <= 60 and m_cp >= 0:
                            members.append({
                                "key":         m_key,
                                "dbid":        m_dbid,
                                "name":        m_nick,
                                "pcId":        m_pcid,
                                "class":       get_class_by_pcid(m_pcid),
                                "combatPower": int(m_cp)
                            })
                if members:
                    if force_key > 0:
                        self.current_party_key = force_key
                    self.event_queue.put({"type": "party_info", "members": members})

            # 11. PartyAddMember_NT (37389) & PartyReconnectMember_NT (37410) & ForceAdd/Reconnect (38410, 38427)
            elif opcode in (37389, 37410, 38410, 38427):
                if opcode == 38410:
                    reader.i64()  # partyKey
                m_t = reader.u8()
                m_num = reader.u8()
                m_key = reader.i32()
                reader.u16(); reader.u16(); reader.str()
                m_dbid = reader.i64()
                m_nick = reader.str()
                m_pcid = reader.i32()
                if opcode in (38410, 38427):
                    reader.vi64(); reader.vi64(); reader.i64(); reader.i32()
                    reader.bool()
                    if m_t & 1: reader.str()
                    if m_t & 2: reader.i32()
                    reader.i32(); reader.i32()
                    reader.bool()
                    reader.i32()
                    read_pos(reader)
                    m_cp = reader.i64()
                    reader.u8()
                else:
                    reader.vi64(); reader.vi64(); reader.i32(); reader.i32(); reader.i32(); reader.i32(); reader.i32(); reader.i32(); reader.i64(); reader.i32()
                    read_pos(reader); reader.bool()
                    if m_t & 1: reader.str()
                    if m_t & 2: reader.i32()
                    reader.i32(); reader.i32(); reader.i32(); reader.bool(); reader.bool()
                    if m_t & 4:
                        rb_cnt = reader.v32()
                        for _ in range(rb_cnt):
                            rb_t = reader.u8(); reader.i32(); reader.u8()
                            if rb_t & 1: reader.vi32()
                    m_cp = reader.i64()
                    reader.u8()
                if m_nick and 1 <= m_pcid <= 60 and m_cp >= 0:
                    log(f"PartyAddMember_NT: Nick='{m_nick}', Class={get_class_by_pcid(m_pcid)}, CP={m_cp}")
                    self.event_queue.put({
                        "type": "party_add",
                        "member": {
                            "key":         m_key,
                            "dbid":        m_dbid,
                            "name":        m_nick,
                            "pcId":        m_pcid,
                            "class":       get_class_by_pcid(m_pcid),
                            "combatPower": int(m_cp)
                        }
                    })

            # 11.8. PartyUpdateMemberHPMP_NT (37403) & ForceUpdateMemberHPMP_NT (38443): Confirma key de membro da party em tempo real (Questlog w_)
            elif opcode in (37403, 38443):
                try:
                    m_key  = reader.vi32()
                    hp     = reader.vi64()
                    hp_max = reader.vi64()
                    mp     = reader.i32()
                    mp_max = reader.i32()
                    ap     = reader.i32()
                    ap_max = reader.i32()
                    dp     = reader.i32()
                    dp_max = reader.i32()
                    live   = reader.bool()
                    if m_key > 0 and 0 <= hp <= hp_max <= 100_000_000:
                        self.event_queue.put({
                            "type":   "party_hpmp",
                            "key":    m_key,
                            "hp":     int(hp),
                            "hp_max": int(hp_max),
                            "live":   bool(live)
                        })
                except Exception:
                    pass

            # 12. PartyUpdateMemberStatus_NT (37404) & ForceUpdateMemberStatus_NT (38444)
            elif opcode in (37404, 38444):
                dbid = reader.i64()
                pcid = reader.i32()
                reader.i64(); reader.i32()
                read_pos(reader)
                lvl = reader.i32(); conqueror_lvl = reader.i32(); gear_score = reader.i32()
                guild_name = reader.str(); guild_emblem = reader.i32()
                if opcode == 37404:
                    reader.bool()  # canTakeDropItem
                cp = reader.i64()
                reader.u8()
                if 0 <= cp <= 10_000_000:
                    self.event_queue.put({"type": "party_update", "dbid": dbid, "pcId": pcid, "combatPower": int(cp)})

            # 12.5. ForceRemoveMember_NT (38434): Membro específico removido
            elif opcode == 38434:
                if (from_lz4 or self.is_synced) and end - start == 17:
                    member_dbid = reader.i64()
                    p_key       = reader.i64()
                    reason      = reader.u8()
                    if member_dbid > 0 and p_key > 0 and 0 <= reason <= 10:
                        log(f"ForceRemoveMember_NT: dbid={member_dbid}")
                        self.event_queue.put({"type": "party_remove_dbid", "dbid": member_dbid})

            # 12.8. PartyFinderGroup_NT (38658) & PartyFinderJoin_NT (38667): Membros do Grupo Random / Matchmaking (Questlog j4 / U_)
            elif opcode == 38658:
                try:
                    reader.i32(); reader.str(); reader.u8(); reader.i32()
                    reader.u8(); reader.u8()
                    reader.i64()  # leaderDbid
                    reader.bool(); reader.u8(); reader.u8()
                    m_cnt = reader.v32()
                    members = []
                    for _ in range(m_cnt):
                        ut = reader.u8()
                        reader.u8()  # number
                        m_dbid = int(reader.i64())
                        m_nick = reader.str()
                        m_pcid = reader.i32()
                        reader.i32(); reader.i32()  # level, equipItemLevel
                        reader.bool()
                        if ut & 2: reader.bool()
                        if ut & 4: reader.u16(); reader.u16()
                        reader.u8()
                        m_cp = int(reader.i64())
                        reader.u8()
                        if ut & 16: reader.i64()
                        reader.u8(); reader.u8()
                        if m_dbid != 0 and m_nick and 1 <= m_pcid <= 60:
                            members.append({
                                "key":         0,
                                "dbid":        m_dbid,
                                "name":        m_nick,
                                "pcId":        m_pcid,
                                "class":       get_class_by_pcid(m_pcid),
                                "combatPower": m_cp if m_cp > 0 else 0
                            })
                    if members:
                        self.event_queue.put({"type": "party_finder_info", "members": members})
                except Exception:
                    pass

            elif opcode == 38667:
                try:
                    ut = reader.u8()
                    reader.u8()
                    m_dbid = int(reader.i64())
                    m_nick = reader.str()
                    m_pcid = reader.i32()
                    reader.i32(); reader.i32()
                    reader.bool()
                    if ut & 2: reader.bool()
                    if ut & 4: reader.u16(); reader.u16()
                    reader.u8()
                    m_cp = int(reader.i64())
                    reader.u8()
                    if ut & 16: reader.i64()
                    reader.u8(); reader.u8()
                    if m_dbid != 0 and m_nick and 1 <= m_pcid <= 60:
                        self.event_queue.put({
                            "type": "party_add",
                            "member": {
                                "key":         0,
                                "dbid":        m_dbid,
                                "name":        m_nick,
                                "pcId":        m_pcid,
                                "class":       get_class_by_pcid(m_pcid),
                                "combatPower": m_cp if m_cp > 0 else 0
                            }
                        })
                except Exception:
                    pass

            # 13. Saída / Desmanche / Kick do Grupo (Validação Estrita l.exact + Sincronia para evitar falsos positivos em combate)
            elif opcode in (37395, 37663, 37407, 37401, 38426, 38446):
                if not (from_lz4 or self.is_synced):
                    return
                pkt_size = end - start
                valid_leave = False
                if opcode == 37395:  # PartyLeave_RS: {result: u16} (2 bytes)
                    if pkt_size == 2 and reader.u16() == 0:
                        valid_leave = True
                elif opcode in (37663, 38446):  # PartyLeave_NT / ForceLeave_NT: {partyKey: i64, reason: u8} (9 bytes)
                    if pkt_size == 9:
                        p_key  = reader.i64()
                        reason = reader.u8()
                        if p_key > 0 and 0 <= reason <= 10 and (self.current_party_key == 0 or p_key == self.current_party_key):
                            valid_leave = True
                elif opcode == 37407:  # PartyDisband_NT: {reason: u8} (1 byte)
                    if from_lz4 and pkt_size == 1 and 0 <= reader.u8() <= 10:
                        valid_leave = True
                elif opcode == 37401:  # PartyKickout_NT: {byVote: bool} (1 byte)
                    if from_lz4 and pkt_size == 1 and reader.u8() in (0, 1):
                        valid_leave = True
                elif opcode == 38426:  # ForceDisband_NT: {} (0 bytes)
                    if from_lz4 and pkt_size == 0:
                        valid_leave = True

                if valid_leave:
                    self.current_party_key = 0
                    log(f"PartyLeft / Disbanded (opcode={opcode})")
                    self.event_queue.put({"type": "party_left"})

        except Exception as ex:
            pass

# ─────────────────────────────────────────────
# DETECÇÃO DINÂMICA DE INTERFACE DE REDE
# ─────────────────────────────────────────────
def get_best_capture_interfaces():
    """
    Retorna uma lista ordenada de interfaces candidatas para o tshark capturar tráfego do Aion 2.
    1. Verifica config.json ('network_interface').
    2. Detecta o IP local ativo e busca o adaptador NPF correspondente no Registro do Windows.
    3. Executa 'tshark -D' para obter os índices dos adaptadores físicos (Ethernet / Realtek / Wi-Fi).
    4. Adiciona adaptadores NPF registrados no Npcap.
    5. Fallback numérico padrão.
    """
    candidates = []

    # 1. Config manual
    try:
        cfg = load_config()
        manual_iface = cfg.get("network_interface")
        if manual_iface and str(manual_iface).lower() not in ("auto", "none", ""):
            candidates.append(str(manual_iface))
    except Exception:
        pass

    # 2. IP local ativo -> GUID do Registro
    active_guid = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        active_ip = s.getsockname()[0]
        s.close()
    except Exception:
        active_ip = None

    if active_ip and sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces')
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                    skey = winreg.OpenKey(key, sub)
                    for val_name in ('DhcpIPAddress', 'IPAddress'):
                        try:
                            val, _ = winreg.QueryValueEx(skey, val_name)
                            val_ips = val if isinstance(val, list) else [val] if isinstance(val, str) else []
                            if active_ip in val_ips:
                                active_guid = sub.upper()
                                npf_dev = rf'\Device\NPF_{active_guid}'
                                if npf_dev not in candidates:
                                    candidates.append(npf_dev)
                                break
                        except Exception:
                            pass
                    winreg.CloseKey(skey)
                    if active_guid:
                        break
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception:
            pass

    # 3. Consulta 'tshark -D'
    try:
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        res = subprocess.run([TSHARK_PATH, "-D"], capture_output=True, text=True, errors="ignore", timeout=3, creationflags=creation_flags)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                # Formato: 1. \Device\NPF_{GUID} (Nome descritivo)
                m = re.match(r"^(\d+)\.\s+(\S+)(?:\s+\((.*)\))?", line)
                if m:
                    idx, dev_name, desc = m.group(1), m.group(2), m.group(3) or ""
                    full_str = f"{dev_name} {desc}".lower()
                    if active_guid and active_guid.lower() in full_str:
                        if idx not in candidates: candidates.insert(0, idx)
                        if dev_name not in candidates: candidates.insert(1, dev_name)
                        continue
                    if any(bad in full_str for bad in ("loopback", "cisco", "sshdump", "udpdump", "wifidump", "remote")):
                        continue
                    if any(good in full_str for good in ("realtek", "ethernet", "wi-fi", "wireless", "gigabit", "intel", "killer", "lan")):
                        if idx not in candidates: candidates.append(idx)
                        if dev_name not in candidates: candidates.append(dev_name)
                    else:
                        if idx not in candidates: candidates.append(idx)
    except Exception:
        pass

    # 4. Outros adaptadores NPF no Npcap
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Services\npcap\Parameters\Adapters')
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                    if sub.startswith('{'):
                        dev = rf'\Device\NPF_{sub.upper()}'
                        if dev not in candidates:
                            candidates.append(dev)
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception:
            pass

    # 5. Fallback numérico padrão
    for fallback in ("1", "4", "2", "3", "5"):
        if fallback not in candidates:
            candidates.append(fallback)

    return candidates

# ─────────────────────────────────────────────
# SNIFFER THREAD COM TSHARK E RECONEXÃO DINÂMICA
# ─────────────────────────────────────────────
class SnifferThread(threading.Thread):
    def __init__(self, event_queue):
        super().__init__(daemon=True)
        self.event_queue = event_queue
        self.is_paused   = False
        self.proc        = None
        self.running     = True
        self.dispatcher  = PacketDispatcher(event_queue)
        self.active_interface = None

    def run(self):
        log("Iniciando SnifferThread...")
        while self.running:
            candidates = get_best_capture_interfaces()
            log(f"[Sniffer] Interfaces candidatas detectadas: {candidates}")

            for iface in candidates:
                if not self.running:
                    break
                cmd = [
                    TSHARK_PATH, "-l", "-n",
                    "-i", str(iface),
                    "-f", f"tcp src port {SERVER_PORT}",
                    "-Y", "tcp.payload and not tcp.analysis.retransmission",
                    "-T", "fields",
                    "-E", "separator=|",
                    "-e", "tcp.stream",
                    "-e", "tcp.payload"
                ]
                log(f"[Sniffer] Tentando capturar na interface: {iface} (porta {SERVER_PORT})...")
                try:
                    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                    self.proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, bufsize=1, creationflags=creation_flags
                    )

                    # Verifica se o processo falha imediatamente (ex: interface inexistente ou sem permissão)
                    try:
                        self.proc.wait(timeout=0.6)
                        err_out = ""
                        try:
                            if self.proc.stderr:
                                err_out = self.proc.stderr.read()
                        except Exception:
                            pass
                        log(f"[Sniffer] Interface {iface} falhou (exit={self.proc.returncode}): {err_out.strip()}")
                        continue
                    except subprocess.TimeoutExpired:
                        pass

                    self.active_interface = iface
                    log(f"[Sniffer] Conectado e capturando na interface {iface}!")

                    # Drena stderr continuamente em thread daemon para impedir que o buffer de 4KB encha e trave o tshark
                    def _drain_stderr(pipe):
                        try:
                            for _ in pipe:
                                pass
                        except Exception:
                            pass
                    if self.proc.stderr:
                        threading.Thread(target=_drain_stderr, args=(self.proc.stderr,), daemon=True).start()

                    self.event_queue.put({
                        "type": "sniffer_status",
                        "status": "connected",
                        "interface": str(iface)
                    })

                    for line in self.proc.stdout:
                        if not self.running:
                            break
                        h = line.strip()
                        if not h or self.is_paused:
                            continue
                        try:
                            if "|" in h:
                                stream_str, hex_payload = h.split("|", 1)
                                if not hex_payload:
                                    continue
                                raw = bytes.fromhex(hex_payload)
                                self.dispatcher.push(raw, stream_id=stream_str or "0")
                            else:
                                raw = bytes.fromhex(h)
                                self.dispatcher.push(raw)
                        except Exception:
                            continue

                    if not self.running:
                        break

                    err_msg = ""
                    try:
                        if self.proc.stderr:
                            err_msg = self.proc.stderr.read().strip()
                    except Exception:
                        pass
                    log(f"[Sniffer] Tshark parou na interface {iface}. Erro: {err_msg}")
                    self.event_queue.put({
                        "type": "sniffer_status",
                        "status": "disconnected",
                        "error": err_msg
                    })
                    break
                except Exception as e:
                    log(f"[Sniffer] Exceção ao iniciar interface {iface}: {e}")
                    continue

            if not self.running:
                break
            time.sleep(2.0)

    def stop(self):
        self.running = False
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass

# ─────────────────────────────────────────────
# RENDERIZADOR DE BARRAS FLUTUANTES OTIMIZADO (PRÉ-ALOCADO + CACHE LRU)
# ─────────────────────────────────────────────
TRANSPARENT_KEY = "#010203"
TRANSPARENT_RGB = (1, 2, 3, 255)
HUD_WIDTH       = 438
MONSTER_BAR_H   = 26
PLAYER_BAR_H    = 30

# Paleta oficial Questlog / Aion 2 (Cores completas das classes com preenchimento sólido anti-vazamento)
CLASS_THEMES = {
    "templar": {
        "fill_top":  (48, 105, 178),
        "fill_bot":  (32, 75, 135),
        "track_top": (22, 38, 62),
        "track_bot": (16, 28, 48),
        "accent":    (88, 165, 255),
        "border":    (52, 92, 145)
    },
    "gladiator": {
        "fill_top":  (52, 135, 148),
        "fill_bot":  (36, 98, 110),
        "track_top": (24, 48, 54),
        "track_bot": (18, 36, 42),
        "accent":    (98, 195, 205),
        "border":    (55, 118, 128)
    },
    "sorcerer": {
        "fill_top":  (132, 75, 198),
        "fill_bot":  (96, 48, 152),
        "track_top": (42, 26, 62),
        "track_bot": (30, 18, 48),
        "accent":    (185, 125, 255),
        "border":    (115, 70, 172)
    },
    "elementalist": {
        "fill_top":  (132, 75, 198),
        "fill_bot":  (96, 48, 152),
        "track_top": (42, 26, 62),
        "track_bot": (30, 18, 48),
        "accent":    (185, 125, 255),
        "border":    (115, 70, 172)
    },
    "spiritmaster": {
        "fill_top":  (165, 65, 165),
        "fill_bot":  (125, 42, 125),
        "track_top": (50, 24, 50),
        "track_bot": (36, 16, 36),
        "accent":    (225, 105, 225),
        "border":    (148, 58, 148)
    },
    "cleric": {
        "fill_top":  (182, 95, 172),
        "fill_bot":  (142, 68, 132),
        "track_top": (52, 28, 48),
        "track_bot": (38, 20, 36),
        "accent":    (235, 128, 220),
        "border":    (162, 85, 152)
    },
    "ranger": {
        "fill_top":  (48, 145, 98),
        "fill_bot":  (32, 108, 72),
        "track_top": (20, 48, 34),
        "track_bot": (15, 36, 26),
        "accent":    (82, 205, 142),
        "border":    (48, 128, 88)
    },
    "assassin": {
        "fill_top":  (58, 155, 78),
        "fill_bot":  (42, 118, 58),
        "track_top": (22, 52, 28),
        "track_bot": (16, 38, 22),
        "accent":    (98, 215, 120),
        "border":    (58, 138, 72)
    },
    "chanter": {
        "fill_top":  (182, 120, 52),
        "fill_bot":  (140, 88, 36),
        "track_top": (52, 36, 20),
        "track_bot": (38, 26, 14),
        "accent":    (235, 162, 78),
        "border":    (162, 110, 48)
    },
    "fighter": {
        "fill_top":  (192, 68, 62),
        "fill_bot":  (145, 48, 42),
        "track_top": (54, 24, 22),
        "track_bot": (38, 16, 16),
        "accent":    (245, 98, 92),
        "border":    (172, 62, 58)
    },
    "skill": {
        "fill_top":  (52, 88, 138),
        "fill_bot":  (36, 65, 105),
        "track_top": (24, 32, 46),
        "track_bot": (18, 24, 35),
        "accent":    (88, 148, 228),
        "border":    (62, 88, 128)
    }
}

def _get_theme_bg_rgb(cname, is_dead=False, is_track=False):
    t = CLASS_THEMES.get(cname, CLASS_THEMES["templar"])
    if is_track:
        t_top, t_bot = t["track_top"], t["track_bot"]
        return ((t_top[0] + t_bot[0]) // 2, (t_top[1] + t_bot[1]) // 2, (t_top[2] + t_bot[2]) // 2)
    f_top, f_bot = t["fill_top"], t["fill_bot"]
    if is_dead:
        f_top = (int(f_top[0] * 0.48 + 16), int(f_top[1] * 0.48 + 17), int(f_top[2] * 0.48 + 20))
        f_bot = (int(f_bot[0] * 0.48 + 12), int(f_bot[1] * 0.48 + 13), int(f_bot[2] * 0.48 + 16))
    return ((f_top[0] + f_bot[0]) // 2, (f_top[1] + f_bot[1]) // 2, (f_top[2] + f_bot[2]) // 2)

def _composite_for_colorkey(rgba_im, bg_rgb, alpha_cutoff=75):
    """
    Pré-compõe pixels semitransparentes contra a cor da barra (bg_rgb) com alfa=255
    e zera alfa < alpha_cutoff. Isso elimina 100% das bordas pretas causadas pelo
    colorkey (#010203) do Windows ao renderizar ícones suaves no Tkinter Canvas!
    """
    out = Image.new("RGBA", rgba_im.size, (0, 0, 0, 0))
    px_in = rgba_im.load()
    px_out = out.load()
    w, h = rgba_im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px_in[x, y]
            if a < alpha_cutoff:
                px_out[x, y] = (0, 0, 0, 0)
            else:
                af = a / 255.0
                nr = int(r * af + bg_rgb[0] * (1.0 - af))
                ng = int(g * af + bg_rgb[1] * (1.0 - af))
                nb = int(b * af + bg_rgb[2] * (1.0 - af))
                if (nr, ng, nb) == (1, 2, 3):
                    nb = 4
                px_out[x, y] = (nr, ng, nb, 255)
    return out

def _make_clean_class_pil(fpath):
    """Remove os pixels pretos/sombra escura embutidos nos PNGs originais e realça o brasão da classe."""
    with Image.open(fpath) as raw_img:
        raw = raw_img.convert("RGBA")
    w, h = raw.size
    clean = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px_in = raw.load()
    px_cl = clean.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px_in[x, y]
            if a < 35:
                continue
            mx = max(r, g, b)
            if mx < 52:
                continue
            elif mx < 85:
                a = int(a * ((mx - 52) / 33.0))
            r = min(255, int(r * 1.18 + 14))
            g = min(255, int(g * 1.18 + 14))
            b = min(255, int(b * 1.18 + 14))
            px_cl[x, y] = (r, g, b, a)
    return clean.resize((20, 20), Image.Resampling.LANCZOS)

def _make_thin_swords_pil():
    """Gera ícone vetorial de espadas cruzadas finas e elegantes (supersampling 4x -> 12x12) para o CP."""
    S = 48
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    blade_col = (56, 189, 248, 255)    # #38bdf8
    shine_col = (186, 230, 253, 255)   # #bae6fd
    guard_col = (14, 165, 233, 255)    # #0ea5e9

    # Espada 1: inferior-esquerda -> superior-direita
    d.line([(11, 37), (41, 7)], fill=blade_col, width=4)
    d.line([(12, 35), (41, 6)], fill=shine_col, width=2)
    d.line([(10, 26), (22, 38)], fill=guard_col, width=4)
    d.line([(7, 41), (13, 35)], fill=blade_col, width=4)
    d.ellipse([5, 39, 10, 44], fill=shine_col)

    # Espada 2: inferior-direita -> superior-esquerda
    d.line([(37, 37), (7, 7)], fill=blade_col, width=4)
    d.line([(36, 35), (7, 6)], fill=shine_col, width=2)
    d.line([(26, 38), (38, 26)], fill=guard_col, width=4)
    d.line([(41, 41), (35, 35)], fill=blade_col, width=4)
    d.ellipse([38, 39, 43, 44], fill=shine_col)

    return im.resize((12, 12), Image.Resampling.LANCZOS)

def _make_weed_skull_pil():
    """Gera a caveira exclusiva Aion 2 Weed Metter (Reaper Skull com chifres, crista em V e olhos brilhantes, 14x14)."""
    S = 56
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rim_col  = (153, 27, 27, 255)     # #991b1b
    bone_top = (254, 226, 226, 255)   # #fee2e2
    bone_mid = (252, 165, 165, 255)   # #fca5a5
    bone_jaw = (248, 113, 113, 255)   # #f87171
    eye_glow = (254, 240, 138, 255)   # #fef08a

    # Chifres laterais e domo craniano
    d.polygon([(3, 12), (14, 18), (11, 28)], fill=bone_jaw)
    d.polygon([(52, 12), (41, 18), (44, 28)], fill=bone_jaw)
    d.ellipse([9, 5, 46, 38], fill=rim_col)
    d.ellipse([11, 7, 44, 36], fill=bone_mid)
    d.ellipse([14, 8, 41, 25], fill=bone_top)
    # Maçãs do rosto e mandíbula com 3 presas afiadas
    d.polygon([(9, 25), (16, 20), (19, 36), (11, 34)], fill=bone_mid)
    d.polygon([(46, 25), (39, 20), (36, 36), (44, 34)], fill=bone_mid)
    d.polygon([(15, 32), (40, 32), (37, 49), (18, 49)], fill=bone_jaw)
    d.polygon([(22, 39), (25, 39), (24, 51), (22, 51)], fill=(0, 0, 0, 0))
    d.polygon([(30, 39), (33, 39), (33, 51), (31, 51)], fill=(0, 0, 0, 0))
    # Órbitas oculares anguladas com brilho dourado interno
    d.polygon([(13, 21), (24, 24), (22, 31), (13, 28)], fill=(20, 10, 14, 255))
    d.polygon([(42, 21), (31, 24), (33, 31), (42, 28)], fill=(20, 10, 14, 255))
    d.ellipse([16, 24, 20, 28], fill=eye_glow)
    d.ellipse([35, 24, 39, 28], fill=eye_glow)
    # Cavidade nasal e crista frontal em V (assinatura Weed Metter)
    d.polygon([(27, 27), (24, 35), (27, 37), (31, 35)], fill=(20, 10, 14, 255))
    d.polygon([(24, 10), (27, 19), (31, 10), (27, 14)], fill=rim_col)

    return im.resize((14, 14), Image.Resampling.LANCZOS)

class PillRenderer:
    def __init__(self):
        self.player_cache  = OrderedDict()
        self.monster_cache = OrderedDict()
        self.p_mask = Image.new("L", (HUD_WIDTH, PLAYER_BAR_H), 0)
        ImageDraw.Draw(self.p_mask).rounded_rectangle(
            [0, 0, HUD_WIDTH - 1, PLAYER_BAR_H - 1], radius=6, fill=255
        )
        self.m_mask = Image.new("L", (HUD_WIDTH, MONSTER_BAR_H), 0)
        ImageDraw.Draw(self.m_mask).rounded_rectangle(
            [0, 0, HUD_WIDTH - 1, MONSTER_BAR_H - 1], radius=6, fill=255
        )

        # Gradiente vermelho / coral da barra do monstro (Idêntico ao da foto: Isolation Specialist Rahu - Hard)
        m_grad = Image.new("RGBA", (2, 2))
        m_grad.putpixel((0, 0), (195, 88, 98, 255))
        m_grad.putpixel((1, 0), (220, 110, 120, 255))
        m_grad.putpixel((0, 1), (155, 62, 72, 255))
        m_grad.putpixel((1, 1), (180, 82, 92, 255))
        self.m_full_grad = m_grad.resize((HUD_WIDTH, MONSTER_BAR_H), Image.Resampling.BILINEAR)

    def _quantize_w(self, raw_w):
        if raw_w <= 0: return 0
        if raw_w >= HUD_WIDTH: return HUD_WIDTH
        return (raw_w // 2) * 2

    def get_monster_pill(self, ratio):
        # Exibe APENAS a pílula vermelha sob o nome do boss proporcional ao HP,
        # mantendo todo o restante do topo 100% transparente
        calc_w = int(HUD_WIDTH * ratio)
        min_w = 120
        bar_w = max(min_w, min(HUD_WIDTH - 75, calc_w))
        bar_w = self._quantize_w(bar_w)
        if bar_w in self.monster_cache:
            self.monster_cache.move_to_end(bar_w)
            return self.monster_cache[bar_w]

        out = Image.new("RGBA", (HUD_WIDTH, MONSTER_BAR_H), TRANSPARENT_RGB)
        if bar_w > 4:
            pill_img = Image.new("RGBA", (bar_w, MONSTER_BAR_H), (0, 0, 0, 0))
            grad_crop = self.m_full_grad.crop((0, 0, bar_w, MONSTER_BAR_H))
            pill_mask = Image.new("L", (bar_w, MONSTER_BAR_H), 0)
            ImageDraw.Draw(pill_mask).rounded_rectangle(
                [0, 0, bar_w - 1, MONSTER_BAR_H - 1], radius=6, fill=255
            )
            pill_img.paste(grad_crop, (0, 0), pill_mask)
            d = ImageDraw.Draw(pill_img)
            d.rounded_rectangle(
                [0, 0, bar_w - 1, MONSTER_BAR_H - 1],
                radius=6, outline=(225, 115, 125, 255), width=1
            )
            out.paste(pill_img, (0, 0), pill_mask)

        photo = ImageTk.PhotoImage(out)
        self.monster_cache[bar_w] = photo
        if len(self.monster_cache) > 96:
            self.monster_cache.popitem(last=False)
        return photo

    def get_player_pill(self, class_name, ratio, is_local=False, is_dead=False):
        c_name = class_name if class_name in CLASS_THEMES else "templar"
        theme = CLASS_THEMES[c_name]
        bar_w = self._quantize_w(int(HUD_WIDTH * ratio))
        key = (c_name, bar_w, is_local, is_dead)
        if key in self.player_cache:
            self.player_cache.move_to_end(key)
            return self.player_cache[key]

        # 1. Trilha de fundo (toda a barra) com a cor da classe escura sólida (alfa 255)
        bar_img = Image.new("RGBA", (HUD_WIDTH, PLAYER_BAR_H))
        b_draw = ImageDraw.Draw(bar_img)
        t_top = theme["track_top"]
        t_bot = theme["track_bot"]
        for y in range(PLAYER_BAR_H):
            f = y / max(1, PLAYER_BAR_H - 1)
            r = int(t_top[0] * (1 - f) + t_bot[0] * f)
            g = int(t_top[1] * (1 - f) + t_bot[1] * f)
            b = int(t_top[2] * (1 - f) + t_bot[2] * f)
            b_draw.line([(0, y), (HUD_WIDTH - 1, y)], fill=(r, g, b, 255))

        # 2. Barra de progresso ativa do dano com a cor da classe viva (ou esmaecida/listrada se morto)
        if bar_w > 0:
            f_top = theme["fill_top"]
            f_bot = theme["fill_bot"]
            if is_dead:
                # Esmaece a cor da classe (~48% intensidade + cinza escuro) igual ao Questlog quando o jogador morre
                f_top = (int(f_top[0] * 0.48 + 16), int(f_top[1] * 0.48 + 17), int(f_top[2] * 0.48 + 20))
                f_bot = (int(f_bot[0] * 0.48 + 12), int(f_bot[1] * 0.48 + 13), int(f_bot[2] * 0.48 + 16))

            for y in range(PLAYER_BAR_H):
                f = y / max(1, PLAYER_BAR_H - 1)
                r = int(f_top[0] * (1 - f) + f_bot[0] * f)
                g = int(f_top[1] * (1 - f) + f_bot[1] * f)
                b = int(f_top[2] * (1 - f) + f_bot[2] * f)
                b_draw.line([(0, y), (bar_w - 1, y)], fill=(r, g, b, 255))

            if is_dead and bar_w > 6:
                # Desenha hachuras diagonais sutis (//) na barra do jogador morto (idêntico ao Questlog)
                stripe_col = (
                    min(255, f_top[0] + 18),
                    min(255, f_top[1] + 18),
                    min(255, f_top[2] + 20),
                    255
                )
                for sx in range(-PLAYER_BAR_H, bar_w, 10):
                    x0 = sx
                    y0 = PLAYER_BAR_H - 2
                    x1 = sx + PLAYER_BAR_H - 2
                    y1 = 1
                    if x1 > bar_w - 2:
                        diff = x1 - (bar_w - 2)
                        x1 -= diff
                        y1 += diff
                    if x0 < 4:
                        diff = 4 - x0
                        x0 += diff
                        y0 -= diff
                    if x0 < x1 and y0 > y1:
                        b_draw.line([(x0, y0), (x1, y1)], fill=stripe_col, width=2)

            # Linha divisória branca no final do dano
            if 4 < bar_w < HUD_WIDTH - 2:
                div_alpha = (180, 185, 195, 210) if is_dead else (255, 255, 255, 230)
                b_draw.line([(bar_w - 1, 1), (bar_w - 1, PLAYER_BAR_H - 2)], fill=div_alpha, width=2)

        # 3. Faixa de destaque lateral esquerda (4px) com a cor vibrante da classe
        acc = theme["accent"]
        if is_dead:
            acc = (int(acc[0] * 0.55 + 20), int(acc[1] * 0.55 + 20), int(acc[2] * 0.55 + 24))
        b_draw.rectangle([0, 0, 3, PLAYER_BAR_H - 1], fill=acc + (255,))

        # 4. Borda externa (dourada para local, ou tom da classe para outros)
        outline_col = (248, 151, 10, 255) if is_local else (theme["border"] + (255,))
        outline_w   = 2 if is_local else 1
        b_draw.rounded_rectangle(
            [0, 0, HUD_WIDTH - 1, PLAYER_BAR_H - 1],
            radius=6,
            outline=outline_col,
            width=outline_w
        )

        # 5. Máscara de cantos arredondados sobre o fundo transparente
        out = Image.new("RGBA", (HUD_WIDTH, PLAYER_BAR_H), TRANSPARENT_RGB)
        out.paste(bar_img, (0, 0), self.p_mask)
        photo = ImageTk.PhotoImage(out)
        self.player_cache[key] = photo
        if len(self.player_cache) > 240:
            self.player_cache.popitem(last=False)
        return photo


# ─────────────────────────────────────────────
# INTERFACE GRÁFICA OVERLAY DPS METER (FLUTUANTE)
# ─────────────────────────────────────────────
class OverlayDPSMeter:
    boss_only          = True
    current_map_key    = 0
    is_loading         = False
    loading_started_at = 0.0
    last_map_reset_t   = 0.0

    def __init__(self, root):
        # 1. Janela Principal Nativa (1x1 Offscreen) -> Garante ícone 100% nativo na Barra de Tarefas do Windows 11
        #    com suporte a "Fechar janela" pelo botão direito na Barra de Tarefas, sem qualquer piscada (flicker)!
        self.taskbar_win = root
        self.taskbar_win.title("Aion 2 Weed Metter")
        if os.path.exists(APP_ICON_FILE):
            try:
                self.taskbar_win.iconbitmap(APP_ICON_FILE)
            except Exception:
                pass
        self.taskbar_win.geometry("1x1+-32000+-32000")
        try:
            self.taskbar_win.attributes("-alpha", 0.0)
        except Exception:
            pass
        self.taskbar_win.protocol("WM_DELETE_WINDOW", self.on_close)
        self.taskbar_win.bind("<Unmap>", self._on_taskbar_unmap)
        self.taskbar_win.bind("<Map>", self._on_taskbar_map)

        # 2. Sistema Dual-Layer: Fundo translúcido (60% opacidade) + Frente 100% opaca (textos/números nítidos)
        self.bar_opacity = 0.60

        # Layer 1 (Fundo): Barras das classes, HP do monstro e menu com 60% de opacidade
        self.bg_win = tk.Toplevel(self.taskbar_win)
        self.bg_win.title("Aion 2 Weed Metter Background")
        self.bg_win.overrideredirect(True)
        self.bg_win.geometry(f"{HUD_WIDTH}x68+80+80")
        self.bg_win.attributes("-topmost", True)
        self.bg_win.configure(bg=TRANSPARENT_KEY)
        try:
            self.bg_win.attributes("-transparentcolor", TRANSPARENT_KEY)
            self.bg_win.attributes("-alpha", self.bar_opacity)
        except Exception:
            pass

        # Layer 2 (Frente): Textos, números, CP e ícones 100% sólidos/opacos para máxima nitidez
        self.root = tk.Toplevel(self.taskbar_win)
        self.root.title("Aion 2 Weed Metter")
        self.root.overrideredirect(True)
        self.root.geometry(f"{HUD_WIDTH}x68+80+80")
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT_KEY)
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
            self.root.attributes("-alpha", 1.0)
        except Exception:
            pass

        self._cur_win_x = 80
        self._cur_win_y = 80
        self._cur_win_h = 68

        # REGRA UNIVERSAL: NUNCA pré-selecionar nenhum personagem ao iniciar o medidor!
        # O medidor SEMPRE inicia em estado neutro ("Aguardando identificar jogador")
        # e identifica o personagem estritamente através dos pacotes em tempo real do Aion 2.
        self.player_identified  = False
        self.local_player_name  = "Aguardando identificar jogador"
        self.local_player_key   = None
        self.local_dbid         = 0
        self.local_class        = None
        self.local_combat_power = 0
        self.current_map_id     = None
        self.current_map_key    = 0
        self.is_loading         = False
        self.loading_started_at = 0.0
        self.last_map_reset_t   = 0.0
        self.account_characters = []

        self.players_names      = {}  # key -> name
        self.players_by_dbid    = {}  # dbid -> name
        self.dbid_to_key        = {}  # dbid -> entity key (CharAppear_NT / PartyInfo_NT)
        self.key_to_char        = {}  # key -> {'dbid': int, 'name': str, 'class': str, 'combatPower': int}
        self.provisional_keys   = set()  # keys associadas provisoriamente quando sk_id=0
        self.players_info       = {}  # name -> {'class': str, 'combatPower': int, 'deaths': int}
        cfg = load_config()
        self.known_chars   = cfg.get("known_chars", {})
        known_chars        = self.known_chars
        if isinstance(known_chars, dict):
            for k_name, k_data in known_chars.items():
                if isinstance(k_data, dict):
                    self.players_info[k_name] = {
                        "class":       k_data.get("class", "templar"),
                        "combatPower": int(k_data.get("combatPower", 0))
                    }

        self.party_members = {}  # name -> {'key': int, 'dbid': int, 'class': str, 'combatPower': int, 'deaths': int}
        self.party_member_keys = set()  # keys confirmadas por PartyUpdateMemberHPMP_NT / ForceUpdateMemberHPMP_NT
        self.npc_registry  = {}  # key -> {'name', 'pcId', 'hp', 'hpMax', 'berserk_ms', 'in_combat'}
        self.summon_owners = {}  # summon_npc_key -> owner_player_key (parentKey do NpcAppear_NT)

        # Estado de Combate, Alvo e Enrage Timer
        self.server_offset_ms            = None
        self.active_target_key           = None
        self.active_target_name          = "Nenhum alvo"
        self.active_target_cur_hp        = None
        self.active_target_max_hp        = None
        self.active_target_berserk_ms    = 0
        self.active_target_berserk_epoch = None
        self.target_is_dead              = False

        # Rastreamento de Encontros e Bosses idêntico ao Questlog (combat.cjs)
        self.encounter_targets       = {}   # target_key -> total damage recebido no encontro
        self.encounter_has_boss      = False
        self.encounter_boss_keys     = set()
        self.active_boss_key         = None
        self.boss_only               = cfg.get("boss_only", True)
        self.combat_frozen           = False
        self.killed_boss_names       = set()
        self.player_dead_state       = {}   # name_lower -> {'is_dead': bool, 'last_death_t': float, 'deaths': int}

        self.players_combat = {}
        self.in_combat      = False
        self.is_paused      = False
        self.is_click_through = False
        self._win32_transparent_applied = False
        self._taskbar_registered = False
        self._f8_was_down   = False
        self.combat_start   = None
        self.last_hit_t     = None
        self.view_mode      = "SOLO"  # "SOLO" (Jogadores) ou "SKILLS" (Habilidades)
        self.visible_rows   = 0
        self.is_hovered     = False
        self._last_enrage_sec = 0
        self._last_z_check_sec = 0
        self._has_pending_skill_icons = False

        self._drag_x       = 0
        self._drag_y       = 0
        self._press_root_x = 0
        self._press_root_y = 0

        self.btns_boss  = []
        self.btns_mode  = []
        self.btns_pause = []
        self.btns_lock  = []

        self.pill_renderer = PillRenderer()
        self.class_icons   = {}
        self.cp_icons      = {}
        self.skull_icons   = {}
        self.load_class_icons()

        self.event_queue = queue.Queue()
        self.sniffer     = SnifferThread(self.event_queue)

        self.build_ui()
        self.show_standby_local_player()
        self.root.after(50, self._apply_win32_overlay_styles)
        self.sniffer.start()

        self.root.bind("<Enter>", self.on_hover_enter)
        self.root.bind("<Leave>", self.on_hover_leave)
        if hasattr(self, "bg_win") and self.bg_win:
            self.bg_win.bind("<Enter>", self.on_hover_enter)
            self.bg_win.bind("<Leave>", self.on_hover_leave)
        self.update_loop()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _on_taskbar_unmap(self, event=None):
        if event is None or event.widget == self.taskbar_win:
            try:
                self.root.withdraw()
                if hasattr(self, "bg_win") and self.bg_win:
                    self.bg_win.withdraw()
            except Exception:
                pass

    def _on_taskbar_map(self, event=None):
        if event is None or event.widget == self.taskbar_win:
            try:
                if hasattr(self, "bg_win") and self.bg_win:
                    self.bg_win.deiconify()
                    self.bg_win.attributes("-topmost", True)
                self.root.deiconify()
                self.root.attributes("-topmost", True)
                self._apply_win32_overlay_styles()
                self._enforce_z_order()
            except Exception:
                pass

    def _get_win_hwnd(self, win):
        if sys.platform != "win32" or not win:
            return 0
        try:
            hwnd = win.winfo_id()
            parent = ctypes.windll.user32.GetParent(hwnd)
            return parent if parent else hwnd
        except Exception:
            return 0

    def _get_top_hwnd(self):
        return self._get_win_hwnd(self.root)

    def _enforce_z_order(self):
        """Garante que self.root (textos/botões) fique SEMPRE estritamente acima de self.bg_win (fundo 60%)."""
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            flags = 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
            h_fg = self._get_win_hwnd(self.root)
            h_bg = self._get_win_hwnd(self.bg_win) if hasattr(self, "bg_win") and self.bg_win else 0
            if h_fg:
                user32.SetWindowPos(h_fg, -1, 0, 0, 0, 0, flags)  # HWND_TOPMOST (-1)
            if h_bg and h_fg:
                user32.SetWindowPos(h_bg, h_fg, 0, 0, 0, 0, flags)  # Coloca bg_win imediatamente atrás de root
        except Exception:
            pass

    def _apply_win32_overlay_styles(self):
        """
        Configura atributos nativos Win32 e DWM (Windows 11) na janela flutuante da HUD (self.root e self.bg_win):
        - Sem usar ShowWindow nem loops de <Map> (zero piscadas / zero interferência no cursor!)
        - Desativa sombra/borda/cantos arredondados pesados do DWM (DWMWCP_DONOTROUND + DWMNCRP_DISABLED)
        - Aplica WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE em ambas as janelas para que clicar/arrastar nunca roube foco nem inverta Z-order!
        """
        if sys.platform != "win32":
            return
        try:
            hwnd = self._get_win_hwnd(self.root)
            if not hwnd:
                return

            user32 = ctypes.windll.user32
            dwmapi = ctypes.windll.dwmapi

            # 1. Desativa shaders pesados de composição Não-Cliente do DWM no Windows 11
            val_one = ctypes.c_int(1)
            dwmapi.DwmSetWindowAttribute(hwnd, 2, ctypes.byref(val_one), 4)   # DWMWA_NCRENDERING_POLICY = DWMNCRP_DISABLED (1)
            dwmapi.DwmSetWindowAttribute(hwnd, 3, ctypes.byref(val_one), 4)   # DWMWA_TRANSITIONS_FORCEDISABLED = 1
            dwmapi.DwmSetWindowAttribute(hwnd, 12, ctypes.byref(val_one), 4)  # DWMWA_EXCLUDED_FROM_PEEK = 1
            dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val_one), 4)  # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_DONOTROUND (1)

            # 2. Configura estilos estendidos Win32 na HUD sem esconder/mostrar a janela
            GWL_EXSTYLE       = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW  = 0x00000080
            WS_EX_NOACTIVATE  = 0x08000000

            get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)

            ex_style = get_long(hwnd, GWL_EXSTYLE)
            ex_style |= (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
            if self._win32_transparent_applied:
                ex_style |= WS_EX_TRANSPARENT
            else:
                ex_style &= ~WS_EX_TRANSPARENT
            set_long(hwnd, GWL_EXSTYLE, ex_style)

            # Configura bg_win usando o HWND real de topo (_get_win_hwnd):
            if hasattr(self, "bg_win") and self.bg_win:
                try:
                    hwnd_bg = self._get_win_hwnd(self.bg_win)
                    if hwnd_bg:
                        dwmapi.DwmSetWindowAttribute(hwnd_bg, 2, ctypes.byref(val_one), 4)
                        dwmapi.DwmSetWindowAttribute(hwnd_bg, 3, ctypes.byref(val_one), 4)
                        dwmapi.DwmSetWindowAttribute(hwnd_bg, 12, ctypes.byref(val_one), 4)
                        dwmapi.DwmSetWindowAttribute(hwnd_bg, 33, ctypes.byref(val_one), 4)

                        ex_bg = get_long(hwnd_bg, GWL_EXSTYLE)
                        ex_bg |= (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
                        if self._win32_transparent_applied:
                            ex_bg |= WS_EX_TRANSPARENT
                        else:
                            ex_bg &= ~WS_EX_TRANSPARENT
                        set_long(hwnd_bg, GWL_EXSTYLE, ex_bg)
                except Exception:
                    pass
            self._enforce_z_order()
        except Exception:
            pass

    def _set_win32_transparent(self, transparent):
        """Ativa/desativa WS_EX_TRANSPARENT sob demanda sem recriar a janela."""
        if sys.platform != "win32" or transparent == self._win32_transparent_applied:
            return
        self._win32_transparent_applied = transparent
        try:
            user32 = ctypes.windll.user32
            GWL_EXSTYLE       = -20
            WS_EX_TRANSPARENT = 0x00000020
            get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)

            hwnd = self._get_win_hwnd(self.root)
            if hwnd:
                ex_style = get_long(hwnd, GWL_EXSTYLE)
                if transparent:
                    ex_style |= WS_EX_TRANSPARENT
                else:
                    ex_style &= ~WS_EX_TRANSPARENT
                set_long(hwnd, GWL_EXSTYLE, ex_style)

            if hasattr(self, "bg_win") and self.bg_win:
                hwnd_bg = self._get_win_hwnd(self.bg_win)
                if hwnd_bg:
                    ex_bg = get_long(hwnd_bg, GWL_EXSTYLE)
                    if transparent:
                        ex_bg |= WS_EX_TRANSPARENT
                    else:
                        ex_bg &= ~WS_EX_TRANSPARENT
                    set_long(hwnd_bg, GWL_EXSTYLE, ex_bg)
        except Exception:
            pass

    def _show_hover_controls(self, show):
        if show and not self.is_hovered:
            self.is_hovered = True
            self.hover_frame.place(x=HUD_WIDTH - 144, y=2, width=140, height=22)
            self.hover_frame.lift()
            if hasattr(self, "bg_hover_frame") and self.bg_hover_frame:
                self.bg_hover_frame.place(x=HUD_WIDTH - 144, y=2, width=140, height=22)
                self.bg_hover_frame.lift()
            self.monster_canvas.itemconfigure(self.m_info_txt, state="hidden")
            if hasattr(self, "m_ttd_txt"):
                self.monster_canvas.itemconfigure(self.m_ttd_txt, state="hidden")
            if hasattr(self, "m_info_left"):
                self.monster_canvas.itemconfigure(self.m_info_left, state="hidden")
            self._enforce_z_order()
        elif not show and self.is_hovered:
            self.is_hovered = False
            self.hover_frame.place_forget()
            if hasattr(self, "bg_hover_frame") and self.bg_hover_frame:
                self.bg_hover_frame.place_forget()
            self.monster_canvas.itemconfigure(self.m_info_txt, state="normal")
            if hasattr(self, "m_ttd_txt"):
                self.monster_canvas.itemconfigure(self.m_ttd_txt, state="normal")
            if hasattr(self, "m_info_left"):
                self.monster_canvas.itemconfigure(self.m_info_left, state="normal")

    def _sync_hover_and_click_through(self):
        """
        Sincroniza a barra de controles (📊 🔄 ⏸ 🔓 ✕) e o estado Click-Through:
        - Quando destravado (🔓): WS_EX_TRANSPARENT desligado; mostra controles ao passar o mouse no medidor.
        - Quando travado (🔒): barras de DPS ficam 100% Click-Through (WS_EX_TRANSPARENT ligado),
          mas ao passar o mouse no topo da barra do monstro, libera o clique nos botões para permitir destravar!
        Ultra-otimizado com ctypes GetCursorPos direto (zero lag / zero overhead de DWM).
        """
        try:
            if sys.platform == "win32":
                pt = _Win32Point()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                px, py = pt.x, pt.y
            else:
                px, py = self.root.winfo_pointerxy()

            wx = getattr(self, "_cur_win_x", None)
            wy = getattr(self, "_cur_win_y", None)
            if wx is None or wy is None:
                wx, wy = self.root.winfo_rootx(), self.root.winfo_rooty()
                self._cur_win_x, self._cur_win_y = wx, wy
            ww = HUD_WIDTH
            wh = getattr(self, "_cur_win_h", None)
            if wh is None:
                wh = self.root.winfo_height()
                self._cur_win_h = wh

            in_window = (wx <= px <= wx + ww) and (wy <= py <= wy + wh)
            in_top_bar = (wx <= px <= wx + ww) and (wy - 2 <= py <= wy + MONSTER_BAR_H + 4)

            if not self.is_click_through:
                self._set_win32_transparent(False)
                self._show_hover_controls(in_window)
            else:
                if in_top_bar:
                    self._set_win32_transparent(False)
                    self._show_hover_controls(True)
                else:
                    self._show_hover_controls(False)
                    self._set_win32_transparent(True)
        except Exception:
            pass

    def toggle_click_through(self):
        self.is_click_through = not self.is_click_through
        for b in self.btns_lock:
            if self.is_click_through:
                b.configure(text="🔒", fg="#f59e0b")
            else:
                b.configure(text="🔓", fg="#cbd5e1")
        self._sync_hover_and_click_through()
        self._update_target_label(is_dead=self.target_is_dead, dur=self._get_fight_duration() if self.in_combat else 0.0)

    def load_class_icons(self):
        # 1. Pré-renderiza as espadinhas finas do CP e a caveira exclusiva Aion 2 Weed Metter
        #    pré-compostas contra cada tema de classe (barra cheia e trilha escura), eliminando 100% das bordas pretas!
        try:
            raw_swords = _make_thin_swords_pil()
            raw_skull  = _make_weed_skull_pil()
            for cname in CLASS_THEMES:
                for is_dead in (False, True):
                    for is_track in (False, True):
                        bg_rgb = _get_theme_bg_rgb(cname, is_dead=is_dead, is_track=is_track)
                        self.cp_icons[(cname, is_dead, is_track)]    = ImageTk.PhotoImage(_composite_for_colorkey(raw_swords, bg_rgb, alpha_cutoff=65))
                        self.skull_icons[(cname, is_dead, is_track)] = ImageTk.PhotoImage(_composite_for_colorkey(raw_skull, bg_rgb, alpha_cutoff=75))
        except Exception:
            pass

        # 2. Carrega e limpa os brasões de classe (removendo a sombra preta embutida e pré-compondo contra a cor da classe)
        if not os.path.exists(CLASS_ICONS_DIR):
            return
        for cname in ["gladiator", "templar", "assassin", "ranger", "sorcerer", "elementalist", "spiritmaster", "cleric", "chanter", "fighter"]:
            fname = "spiritmaster.png" if cname in ("elementalist", "spiritmaster") else f"{cname}.png"
            fpath = os.path.join(CLASS_ICONS_DIR, fname)
            if os.path.exists(fpath):
                try:
                    clean_pil = _make_clean_class_pil(fpath)
                    for is_dead in (False, True):
                        bg_rgb = _get_theme_bg_rgb(cname, is_dead=is_dead, is_track=False)
                        photo = ImageTk.PhotoImage(_composite_for_colorkey(clean_pil, bg_rgb, alpha_cutoff=75))
                        self.class_icons[(cname, is_dead)] = photo
                    self.class_icons[cname] = self.class_icons[(cname, False)]
                except Exception:
                    pass

    def start_move(self, event):
        if self.is_click_through:
            return
        self._drag_x       = event.x_root - self.root.winfo_x()
        self._drag_y       = event.y_root - self.root.winfo_y()
        self._press_root_x = event.x_root
        self._press_root_y = event.y_root
        self._enforce_z_order()

    def do_move(self, event):
        if self.is_click_through:
            return
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self._cur_win_x = x
        self._cur_win_y = y
        self.root.geometry(f"+{x}+{y}")
        if hasattr(self, "bg_win") and self.bg_win:
            self.bg_win.geometry(f"+{x}+{y}")
        if sys.platform == "win32":
            try:
                flags = 0x0001 | 0x0010  # SWP_NOSIZE | SWP_NOACTIVATE (mantém root acima de bg_win!)
                h_fg = self._get_win_hwnd(self.root)
                h_bg = self._get_win_hwnd(self.bg_win) if hasattr(self, "bg_win") and self.bg_win else 0
                if h_fg:
                    ctypes.windll.user32.SetWindowPos(h_fg, -1, x, y, 0, 0, flags)
                if h_bg and h_fg:
                    ctypes.windll.user32.SetWindowPos(h_bg, h_fg, x, y, 0, 0, flags)
            except Exception:
                pass

    def on_bar_release(self, event):
        if self.is_click_through:
            return
        self._enforce_z_order()
        # Se foi um clique curto (sem arrastar a janela), alterna entre Jogadores e Habilidades!
        dx = abs(event.x_root - self._press_root_x)
        dy = abs(event.y_root - self._press_root_y)
        if dx < 5 and dy < 5:
            self.toggle_mode()

    def minimize_window(self):
        self.taskbar_win.iconify()

    def get_player_cp(self, name, caster_key=None, is_local=False):
        if is_local:
            return self.local_combat_power
        if not name:
            return 0
        name_low = name.lower()

        # 1. Busca direta em players_info (exato e case-insensitive)
        if name in self.players_info and self.players_info[name].get("combatPower", 0) > 0:
            return self.players_info[name]["combatPower"]
        for p_n, p_inf in self.players_info.items():
            if p_n.lower() == name_low and p_inf.get("combatPower", 0) > 0:
                return p_inf["combatPower"]

        # 2. Busca em party_members (por nome case-insensitive ou por caster_key)
        for m_n, m_data in self.party_members.items():
            if (m_n.lower() == name_low or (caster_key and m_data.get("key") == caster_key)) and m_data.get("combatPower", 0) > 0:
                return m_data["combatPower"]

        # 3. Busca em known_chars (persistido em config.json)
        if isinstance(self.known_chars, dict):
            if name in self.known_chars and isinstance(self.known_chars[name], dict) and self.known_chars[name].get("combatPower", 0) > 0:
                return self.known_chars[name]["combatPower"]
            for k_n, k_data in self.known_chars.items():
                if k_n.lower() == name_low and isinstance(k_data, dict) and k_data.get("combatPower", 0) > 0:
                    return k_data["combatPower"]

        return 0

    def _remember_player(self, name, p_class=None, cp=0, key=None, dbid=None, is_party_or_local=False):
        if not name or name in ("Você", "Aguardando Alvo", "Aguardando identificar jogador"):
            return
        if dbid and int(dbid) > 0:
            self.players_by_dbid[int(dbid)] = name
        if name not in self.players_info:
            self.players_info[name] = {}
        if p_class:
            self.players_info[name]["class"] = p_class
        if cp and cp > 0:
            self.players_info[name]["combatPower"] = int(cp)
            if is_party_or_local:
                save_known_char(name, p_class or self.players_info[name].get("class"), int(cp))
            if not isinstance(self.known_chars, dict):
                self.known_chars = {}
            if name not in self.known_chars:
                self.known_chars[name] = {}
            self.known_chars[name]["combatPower"] = int(cp)
            if p_class:
                self.known_chars[name]["class"] = p_class
        if key:
            self.players_names[key] = name
        # Atualiza combatPower imediatamente em players_combat se já estiver na tabela da luta atual:
        if name in self.players_combat:
            if cp and cp > 0:
                self.players_combat[name]["combatPower"] = int(cp)
            if p_class:
                self.players_combat[name]["class"] = p_class
        if key:
            for c_k, c_data in self.players_combat.items():
                if c_data.get("caster_key") == key:
                    c_data["name"] = name
                    if cp and cp > 0:
                        c_data["combatPower"] = int(cp)
                    if p_class:
                        c_data["class"] = p_class

    def edit_row_player(self, row_idx):
        if self.is_click_through:
            return
        sorted_players = sorted(
            self.players_combat.values(),
            key=lambda x: x["damage"],
            reverse=True
        )
        if row_idx >= len(sorted_players):
            self.edit_player_name()
            return
        p = sorted_players[row_idx]
        p_name = p["name"]
        if p.get("is_local", False):
            self.edit_player_name()
            return

        self._set_win32_transparent(False)
        curr_cp = self.get_player_cp(p_name, p.get("caster_key"))
        init_cp = f"{curr_cp/1000:.1f}K" if curr_cp >= 1000 else (str(curr_cp) if curr_cp > 0 else "")
        new_val = simpledialog.askstring(
            f"Combat Power de {p_name}",
            f"Defina o Combat Power (CP) de {p_name}:\n(Exemplos: 105.9k, 112k, 105900)",
            initialvalue=init_cp,
            parent=self.root
        )
        self._sync_hover_and_click_through()
        if new_val and new_val.strip():
            raw = new_val.strip().lower().replace("k", "000").replace("m", "000000").replace(".", "").replace(",", "")
            try:
                cp_num = int(raw)
                if 100 <= cp_num <= 10_000_000:
                    self._remember_player(p_name, p.get("class"), cp_num, p.get("caster_key"))
                    p["combatPower"] = cp_num
                    self.render_hud(self._get_fight_duration())
            except Exception:
                pass

    def edit_player_name(self):
        if self.is_click_through:
            return
        self._set_win32_transparent(False)
        init_val = self.local_player_name if self.player_identified else ""
        new_name = simpledialog.askstring(
            "Alterar Jogador Local",
            "Digite exatamente o nome do seu personagem no Aion 2:",
            initialvalue=init_val,
            parent=self.root
        )
        self._sync_hover_and_click_through()
        if new_name and new_name.strip():
            self.local_player_name = new_name.strip()
            self.player_identified = True
            # Restaura classe e CP conhecidos se já registrados anteriormente
            for p_n, p_inf in self.players_info.items():
                if p_n.lower() == self.local_player_name.lower():
                    if p_inf.get("class"):
                        self.local_class = p_inf["class"]
                    if p_inf.get("combatPower", 0) > 0 and self.local_combat_power == 0:
                        self.local_combat_power = p_inf["combatPower"]
                    break
            save_known_char(self.local_player_name, self.local_class, self.local_combat_power)
            save_config({
                "last_local_player": {
                    "name": self.local_player_name,
                    "class": self.local_class or "templar",
                    "combatPower": self.local_combat_power
                }
            })
            if not self.in_combat:
                self.show_standby_local_player()

    def on_hover_enter(self, event=None):
        self._sync_hover_and_click_through()

    def on_hover_leave(self, event=None):
        self.root.after(120, self._sync_hover_and_click_through)

    def toggle_boss_only(self):
        self.boss_only = not self.boss_only
        cfg = load_config()
        cfg["boss_only"] = self.boss_only
        save_config(cfg)
        icon = "👑" if self.boss_only else "🎯"
        color = "#f59e0b" if self.boss_only else "#94a3b8"
        for b in self.btns_boss:
            try:
                b.config(text=icon, fg=color)
            except Exception:
                pass
        if self.boss_only and not self.encounter_has_boss and not self.active_boss_key:
            self.reset_metrics()

    def _populate_control_buttons(self, parent_frame):
        """Cria os 6 botões de controle (👑/🎯 📊 🔄 ⏸ 🔓 ✕) em ambos os layers para garantir clique 100% confiável."""
        def _bind_btn(btn, callback):
            def _on_press(e):
                callback()
                return "break"
            btn.bind("<ButtonPress-1>", _on_press)
            btn.bind("<ButtonRelease-1>", lambda e: "break")
            btn.bind("<Enter>", self.on_hover_enter)

        boss_icon = "👑" if self.boss_only else "🎯"
        boss_color = "#f59e0b" if self.boss_only else "#94a3b8"
        b_boss = tk.Label(
            parent_frame, text=boss_icon, fg=boss_color, bg="#18141a",
            font=("Segoe UI", 9, "bold"), cursor="hand2", padx=3
        )
        b_boss.pack(side=tk.LEFT)
        _bind_btn(b_boss, self.toggle_boss_only)
        self.btns_boss.append(b_boss)

        b_mode = tk.Label(
            parent_frame, text="📊", fg="#38bdf8", bg="#18141a",
            font=("Segoe UI", 9, "bold"), cursor="hand2", padx=3
        )
        b_mode.pack(side=tk.LEFT)
        _bind_btn(b_mode, self.toggle_mode)
        self.btns_mode.append(b_mode)

        b_reset = tk.Label(
            parent_frame, text="🔄", fg="#cbd5e1", bg="#18141a",
            font=("Segoe UI", 9), cursor="hand2", padx=3
        )
        b_reset.pack(side=tk.LEFT)
        _bind_btn(b_reset, self.reset_metrics)

        b_pause = tk.Label(
            parent_frame, text="⏸", fg="#cbd5e1", bg="#18141a",
            font=("Segoe UI", 9), cursor="hand2", padx=3
        )
        b_pause.pack(side=tk.LEFT)
        _bind_btn(b_pause, self.toggle_pause)
        self.btns_pause.append(b_pause)

        b_lock = tk.Label(
            parent_frame, text="🔓", fg="#cbd5e1", bg="#18141a",
            font=("Segoe UI", 9), cursor="hand2", padx=3
        )
        b_lock.pack(side=tk.LEFT)
        _bind_btn(b_lock, self.toggle_click_through)
        self.btns_lock.append(b_lock)

        b_close = tk.Label(
            parent_frame, text="✕", fg="#f87171", bg="#18141a",
            font=("Segoe UI", 9, "bold"), cursor="hand2", padx=3
        )
        b_close.pack(side=tk.LEFT)
        _bind_btn(b_close, self.on_close)

    def build_ui(self):
        # ─────────────────────────────────────────────────────────────
        # 1. LAYER 1 (Fundo - bg_win): Barra Vermelha do Boss + Fundo das Barras + Menu com 60% Opacidade
        # ─────────────────────────────────────────────────────────────
        self.bg_monster_frame = tk.Frame(self.bg_win, bg=TRANSPARENT_KEY, width=HUD_WIDTH, height=MONSTER_BAR_H)
        self.bg_monster_frame.pack(fill=tk.X, pady=(0, 4))
        self.bg_monster_frame.pack_propagate(False)

        self.bg_monster_canvas = tk.Canvas(
            self.bg_monster_frame, bg=TRANSPARENT_KEY,
            width=HUD_WIDTH, height=MONSTER_BAR_H,
            highlightthickness=0, bd=0
        )
        self.bg_monster_canvas.pack(fill=tk.BOTH, expand=True)
        self.m_bg_img = self.bg_monster_canvas.create_image(0, 0, anchor="nw")

        # Vincula eventos de arraste, clique e hover diretamente no canvas do monstro no fundo
        self.bg_monster_canvas.bind("<ButtonPress-1>", self.start_move)
        self.bg_monster_canvas.bind("<B1-Motion>", self.do_move)
        self.bg_monster_canvas.bind("<Button-3>", lambda e: self.edit_player_name())
        self.bg_monster_canvas.bind("<Enter>", self.on_hover_enter)
        self.bg_monster_canvas.bind("<Leave>", self.on_hover_leave)

        # Menu de controles espelhado no bg_win (garante clique 100% mesmo se clicado no layer de fundo)
        self.bg_hover_frame = tk.Frame(self.bg_monster_frame, bg="#18141a")
        self._populate_control_buttons(self.bg_hover_frame)

        self.bg_bars_container = tk.Frame(self.bg_win, bg=TRANSPARENT_KEY)
        self.bg_bars_container.pack(fill=tk.BOTH, expand=True)
        self.bg_rows = [self._make_bg_row(self.bg_bars_container, i) for i in range(6)]

        # ─────────────────────────────────────────────────────────────
        # 2. LAYER 2 (Frente - root): Textos, Números, Ícones e Botões 100% Sólidos e Nítidos
        # ─────────────────────────────────────────────────────────────
        self.monster_frame = tk.Frame(self.root, bg=TRANSPARENT_KEY, width=HUD_WIDTH, height=MONSTER_BAR_H)
        self.monster_frame.pack(fill=tk.X, pady=(0, 4))
        self.monster_frame.pack_propagate(False)

        mc = tk.Canvas(
            self.monster_frame, bg=TRANSPARENT_KEY,
            width=HUD_WIDTH, height=MONSTER_BAR_H,
            highlightthickness=0, bd=0
        )
        mc.pack(fill=tk.BOTH, expand=True)
        self.monster_canvas = mc

        self.m_name_txt   = mc.create_text(12, 13, text="Aguardando Alvo", anchor="w", fill="#ffffff", font=("Segoe UI", 9, "bold"))
        self.m_info_txt   = mc.create_text(HUD_WIDTH - 10, 13, text="", anchor="e", fill="#ffffff", font=("Segoe UI", 9, "bold"))
        self.m_ttd_txt    = mc.create_text(HUD_WIDTH - 50, 13, text="", anchor="e", fill="#f87171", font=("Segoe UI", 9, "bold"))
        self.m_info_left  = mc.create_text(HUD_WIDTH - 120, 13, text="", anchor="e", fill="#ffffff", font=("Segoe UI", 9, "bold"))
        self._m_last_pill  = None
        self._m_last_name  = None
        self._m_last_info  = None
        self._m_last_color = None
        self._m_last_ttd   = None
        self._m_last_left  = None

        mc.bind("<ButtonPress-1>", self.start_move)
        mc.bind("<B1-Motion>", self.do_move)
        mc.bind("<Button-3>", lambda e: self.edit_player_name())
        mc.bind("<Enter>", self.on_hover_enter)
        mc.bind("<Leave>", self.on_hover_leave)

        # Controles interativos no foreground (botões 100% nítidos com fundo sólido para captura de cliques)
        self.hover_frame = tk.Frame(self.monster_frame, bg="#18141a")
        self._populate_control_buttons(self.hover_frame)
        self.btn_mode  = self.btns_mode[-1]
        self.btn_pause = self.btns_pause[-1]
        self.btn_lock  = self.btns_lock[-1]

        self.bars_container = tk.Frame(self.root, bg=TRANSPARENT_KEY)
        self.bars_container.pack(fill=tk.BOTH, expand=True)
        self.rows = [self._make_row(self.bars_container, i) for i in range(6)]

    def _make_bg_row(self, parent, idx):
        f = tk.Frame(parent, bg=TRANSPARENT_KEY, width=HUD_WIDTH, height=PLAYER_BAR_H)
        f.pack_propagate(False)
        c = tk.Canvas(
            f, bg=TRANSPARENT_KEY,
            width=HUD_WIDTH, height=PLAYER_BAR_H,
            highlightthickness=0, bd=0
        )
        c.pack(fill=tk.BOTH, expand=True)
        pill_img = c.create_image(0, 0, anchor="nw")

        c.bind("<ButtonPress-1>", self.start_move)
        c.bind("<B1-Motion>", self.do_move)
        c.bind("<ButtonRelease-1>", self.on_bar_release)
        c.bind("<Button-3>", lambda e, i=idx: self.edit_row_player(i))
        c.bind("<Enter>", self.on_hover_enter)
        c.bind("<Leave>", self.on_hover_leave)

        return {"frame": f, "c": c, "pill": pill_img, "packed": False}

    def _make_row(self, parent, idx):
        f = tk.Frame(parent, bg=TRANSPARENT_KEY, width=HUD_WIDTH, height=PLAYER_BAR_H)
        f.pack_propagate(False)

        c = tk.Canvas(
            f, bg=TRANSPARENT_KEY,
            width=HUD_WIDTH, height=PLAYER_BAR_H,
            highlightthickness=0, bd=0
        )
        c.pack(fill=tk.BOTH, expand=True)

        rank_txt  = c.create_text(12, 15, text="", anchor="center", fill="#cbd5e1", font=("Segoe UI", 9, "bold"))
        icon_img  = c.create_image(28, 15, anchor="center")
        name_txt  = c.create_text(44, 15, text="", anchor="w", fill="#ffffff", font=("Segoe UI", 10, "bold"))
        cp_img    = c.create_image(118, 15, anchor="w")
        cp_txt    = c.create_text(132, 15, text="", anchor="w", fill="#38bdf8", font=("Segoe UI", 8, "bold"))
        death_img = c.create_image(172, 15, anchor="w")
        death_txt = c.create_text(188, 15, text="", anchor="w", fill="#f87171", font=("Segoe UI", 8, "bold"))

        dmg_txt   = c.create_text(HUD_WIDTH - 178, 15, text="", anchor="e", fill="#ffffff", font=("Segoe UI", 10, "bold"))
        dps_txt   = c.create_text(HUD_WIDTH - 120, 15, text="", anchor="e", fill="#cbd5e1", font=("Segoe UI", 9))
        crit_txt  = c.create_text(HUD_WIDTH - 52,  15, text="", anchor="e", fill="#fbbf24", font=("Segoe UI", 8, "bold"))
        share_txt = c.create_text(HUD_WIDTH - 8,   15, text="", anchor="e", fill="#cbd5e1", font=("Segoe UI", 9))

        c.bind("<ButtonPress-1>", self.start_move)
        c.bind("<B1-Motion>", self.do_move)
        c.bind("<ButtonRelease-1>", self.on_bar_release)
        c.bind("<Button-3>", lambda e, i=idx: self.edit_row_player(i))
        c.bind("<Enter>", self.on_hover_enter)
        c.bind("<Leave>", self.on_hover_leave)

        return {
            "idx": idx, "frame": f, "c": c, "rank": rank_txt, "img": icon_img,
            "name": name_txt, "cp_img": cp_img, "cp": cp_txt,
            "death_img": death_img, "death": death_txt,
            "col1": dmg_txt, "col2": dps_txt, "col3": crit_txt, "col4": share_txt,
            "packed": False,
            "_last_pill": None,
            "_last_rank": None,
            "_last_rank_color": None,
            "_last_img":       None,
            "_last_name":      None,
            "_last_cp_img":    None,
            "_last_cp":        None,
            "_last_death_img": None,
            "_last_death":     None,
            "_last_col1":      None,
            "_last_col2":      None,
            "_last_col3":      None,
            "_last_col4":      None,
        }

    def _update_row(
        self, row, pill, img_obj, rank_str, rank_color, name_str, cp_str,
        dmg_str, dps_str, share_str, pad_offset=5, death_str="",
        crit_str="", p_class="templar", is_dead=False, ratio=1.0, show_cp_icon=False
    ):
        """Atualiza a barra visual no fundo (60% opaco) e os textos/ícones na frente (100% nítidos)."""
        idx = row.get("idx", 0)
        if pill is not row["_last_pill"]:
            if hasattr(self, "bg_rows") and idx < len(self.bg_rows):
                self.bg_rows[idx]["c"].itemconfig(self.bg_rows[idx]["pill"], image=pill)
            row["_last_pill"] = pill

        c = row["c"]
        img_val = img_obj if img_obj else ""
        if img_val != row["_last_img"]:
            c.itemconfig(row["img"], image=img_val)
            row["_last_img"] = img_val

        if rank_str != row.get("_last_rank"):
            c.itemconfig(row["rank"], text=rank_str)
            row["_last_rank"] = rank_str

        if rank_color != row.get("_last_rank_color"):
            c.itemconfig(row["rank"], fill=rank_color)
            row["_last_rank_color"] = rank_color

        name_changed  = (name_str != row["_last_name"])
        cp_changed    = (cp_str != row["_last_cp"])
        death_changed = (death_str != row.get("_last_death"))

        if name_changed:
            c.itemconfig(row["name"], text=name_str)
            row["_last_name"] = name_str

        if cp_changed:
            c.itemconfig(row["cp"], text=cp_str)
            row["_last_cp"] = cp_str

        if death_changed:
            c.itemconfig(row["death"], text=death_str)
            row["_last_death"] = death_str

        bar_w = int(HUD_WIDTH * ratio)
        c_theme = p_class if p_class in CLASS_THEMES else "templar"

        bbox_n = c.bbox(row["name"]) if name_str else None
        name_end = (bbox_n[2] + pad_offset) if bbox_n else (46 + len(name_str) * 7 + pad_offset)

        if cp_str:
            if show_cp_icon and hasattr(self, "cp_icons") and self.cp_icons:
                cp_is_track = (name_end >= bar_w)
                cp_ic = self.cp_icons.get((c_theme, is_dead, cp_is_track)) or ""
                if cp_ic != row.get("_last_cp_img"):
                    c.itemconfig(row["cp_img"], image=cp_ic)
                    row["_last_cp_img"] = cp_ic
                c.coords(row["cp_img"], name_end, 15)
                cp_txt_x = name_end + 14
            else:
                if row.get("_last_cp_img"):
                    c.itemconfig(row["cp_img"], image="")
                    row["_last_cp_img"] = ""
                cp_txt_x = name_end
            c.coords(row["cp"], cp_txt_x, 15)
            bbox_cp = c.bbox(row["cp"])
            after_cp_x = (bbox_cp[2] + 6) if bbox_cp else (cp_txt_x + len(cp_str) * 6 + 6)
        else:
            if row.get("_last_cp_img"):
                c.itemconfig(row["cp_img"], image="")
                row["_last_cp_img"] = ""
            after_cp_x = name_end

        if death_str:
            if hasattr(self, "skull_icons") and self.skull_icons:
                sk_is_track = (after_cp_x >= bar_w)
                sk_ic = self.skull_icons.get((c_theme, is_dead, sk_is_track)) or ""
                if sk_ic != row.get("_last_death_img"):
                    c.itemconfig(row["death_img"], image=sk_ic)
                    row["_last_death_img"] = sk_ic
                c.coords(row["death_img"], after_cp_x, 15)
                c.coords(row["death"], after_cp_x + 16, 15)
            else:
                c.coords(row["death"], after_cp_x, 15)
        else:
            if row.get("_last_death_img"):
                c.itemconfig(row["death_img"], image="")
                row["_last_death_img"] = ""

        if dmg_str != row["_last_col1"]:
            c.itemconfig(row["col1"], text=dmg_str)
            row["_last_col1"] = dmg_str

        if dps_str != row["_last_col2"]:
            c.itemconfig(row["col2"], text=dps_str)
            row["_last_col2"] = dps_str

        if crit_str != row.get("_last_col3"):
            c.itemconfig(row["col3"], text=crit_str)
            row["_last_col3"] = crit_str

        if share_str != row.get("_last_col4"):
            c.itemconfig(row["col4"], text=share_str)
            row["_last_col4"] = share_str

    def set_visible_rows(self, count):
        count = max(1, min(len(self.rows), count))
        if count == self.visible_rows:
            return
        for i in range(len(self.rows)):
            r = self.rows[i]
            bg_r = self.bg_rows[i] if hasattr(self, "bg_rows") and i < len(self.bg_rows) else None
            if i < count:
                if not r["packed"]:
                    r["frame"].pack(fill=tk.X, pady=(0, 3))
                    r["packed"] = True
                if bg_r and not bg_r["packed"]:
                    bg_r["frame"].pack(fill=tk.X, pady=(0, 3))
                    bg_r["packed"] = True
            else:
                if r["packed"]:
                    r["frame"].pack_forget()
                    r["packed"] = False
                if bg_r and bg_r["packed"]:
                    bg_r["frame"].pack_forget()
                    bg_r["packed"] = False
        self.visible_rows = count
        new_h = (MONSTER_BAR_H + 3) + count * (PLAYER_BAR_H + 3)
        self._cur_win_h = new_h
        self.root.geometry(f"{HUD_WIDTH}x{new_h}")
        if hasattr(self, "bg_win") and self.bg_win:
            self.bg_win.geometry(f"{HUD_WIDTH}x{new_h}")
        self._enforce_z_order()

    def _get_fight_duration(self):
        """
        Cálculo idêntico ao Questlog (combat.cjs: yt = Math.max(1000, ke - re), seconds = yt / 1000):
        A duração é SEMPRE medida estritamente entre o primeiro hit (combat_start) e o último hit (last_hit_t).
        Nunca adiciona segundos extras após parar de bater ou após a morte do Boss!
        """
        if not self.in_combat or not self.combat_start or not self.last_hit_t:
            return 1.0
        return max(1.0, self.last_hit_t - self.combat_start)

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        self.sniffer.is_paused = self.is_paused
        for b in self.btns_pause:
            if self.is_paused:
                b.configure(text="▶", fg="#22c55e")
            else:
                b.configure(text="⏸", fg="#cbd5e1")

    def toggle_mode(self):
        if self.view_mode == "SOLO":
            self.view_mode = "SKILLS"
            for b in self.btns_mode:
                b.configure(text="👥", fg="#22c55e")
        else:
            self.view_mode = "SOLO"
            for b in self.btns_mode:
                b.configure(text="📊", fg="#38bdf8")

        if self.in_combat and self.combat_start:
            dur = self._get_fight_duration()
            self._update_target_label(is_dead=self.target_is_dead, dur=dur)
            if self.view_mode == "SOLO":
                self.render_hud(dur)
            else:
                self.render_skills(dur)
        else:
            self.show_standby_local_player()

    def reset_metrics(self):
        flush_config_to_disk(force=True)
        self.players_combat.clear()
        self.player_dead_state.clear()
        self.encounter_targets.clear()
        self.encounter_has_boss      = False
        self.encounter_boss_keys.clear()
        self.active_boss_key         = None
        self.active_target_key       = None
        self.combat_start            = None
        self.last_hit_t              = None
        self.in_combat               = False
        self.target_is_dead          = False
        self.combat_frozen           = False
        self.active_target_cur_hp    = None
        self.active_target_max_hp    = None
        self.active_target_berserk_ms = 0
        self.active_target_berserk_epoch = None
        self.active_target_name      = "Nenhum alvo"
        self._has_pending_skill_icons = False
        self.show_standby_local_player()

    def _perform_map_or_loading_reset(self, new_map=None, new_map_key=0, clear_keys=True, set_loading=False, now=None, reset_map_id=False):
        """Limpa entidades da instância/mapa anterior e reseta métricas preservando a identidade do jogador local."""
        cur_t = now if now is not None else time.time()
        if reset_map_id:
            self.current_map_id = None
        elif new_map is not None:
            self.current_map_id = new_map
        self.current_map_key = new_map_key or 0
        self.npc_registry.clear()
        self.summon_owners.clear()
        self.killed_boss_names.clear()
        if clear_keys:
            self.party_member_keys.clear()
            self.provisional_keys.clear()
            self.dbid_to_key.clear()
            self.key_to_char.clear()
            self.local_player_key = None
            self.players_names.clear()
            for m_name, m_data in self.party_members.items():
                m_data["key"] = 0
        self.is_loading = bool(set_loading)
        if set_loading:
            self.loading_started_at = cur_t
        self.last_map_reset_t = cur_t
        self.reset_metrics()

    def show_standby_local_player(self):
        if not self.rows:
            return
        # Exibe APENAS 1 barra do monstro + 1 barra do jogador (sem linhas vazias!)
        self.set_visible_rows(1)
        self._update_target_label(is_dead=False, dur=0.0)

        row = self.rows[0]
        if not self.player_identified:
            pill = self.pill_renderer.get_player_pill("skill", 1.0, is_local=False)
            self._update_row(
                row, pill, None,
                "-", "#cbd5e1",
                "Aguardando identificar jogador", "",
                "", "", "", death_str="", crit_str="",
                p_class="skill", is_dead=False, ratio=1.0, show_cp_icon=False
            )
            return

        p_class = self.local_class or "templar"
        pill    = self.pill_renderer.get_player_pill(p_class, 1.0, is_local=True)
        c_icon  = self.class_icons.get((p_class, False)) or self.class_icons.get(p_class)
        cp_val  = self.local_combat_power
        cp_str  = f"{cp_val/1000:.1f}K" if cp_val >= 1000 else (f"{cp_val}" if cp_val > 0 else "")

        self._update_row(
            row, pill, c_icon,
            "1", "#f59e0b",
            self.local_player_name, cp_str,
            "0", "0/s", "0.0%", death_str="",
            crit_str="0% (0)",
            p_class=p_class, is_dead=False, ratio=1.0, show_cp_icon=bool(cp_str)
        )

    def _compute_berserk_epoch(self, berserk_ms):
        if not berserk_ms or berserk_ms <= 0:
            return None
        if self.server_offset_ms is not None:
            return (berserk_ms - self.server_offset_ms) / 1000.0
        return None

    def _resolve_player_name_by_key(self, ekey):
        if not ekey:
            return None
        if self.local_player_key and ekey == self.local_player_key:
            return self.local_player_name if self.player_identified else None
        if ekey in self.players_names:
            return self.players_names[ekey]
        for m_name, m_data in self.party_members.items():
            if m_data.get("key") == ekey:
                return m_name
        return None

    def _mark_player_dead(self, ekey, now_t):
        """Marca o jogador como morto e incrementa o contador de mortes (💀 N) igual ao Questlog."""
        if not self.in_combat or self.combat_frozen:
            return False
        p_name = self._resolve_player_name_by_key(ekey)
        if not p_name:
            return False
        low_n = p_name.lower()
        st = self.player_dead_state.get(low_n)
        if not st:
            st = {"is_dead": False, "last_death_t": 0.0, "deaths": 0}
            self.player_dead_state[low_n] = st
        changed = False
        if not st["is_dead"]:
            st["is_dead"] = True
            changed = True
            if now_t - st["last_death_t"] > 2.0:
                st["deaths"] += 1
                st["last_death_t"] = now_t

        for p in self.players_combat.values():
            if p["name"].lower() == low_n or (p["is_local"] and self.player_identified and low_n == self.local_player_name.lower()):
                if p.get("is_dead") != st["is_dead"] or p.get("deaths", 0) != st["deaths"]:
                    p["is_dead"] = st["is_dead"]
                    p["deaths"]  = st["deaths"]
                    changed = True
        return changed

    def _mark_player_alive(self, ekey):
        """Remove o estado esmaecido quando o jogador ressuscita durante a luta, mantendo o contador 💀 N."""
        if not self.in_combat or self.combat_frozen:
            return False
        p_name = self._resolve_player_name_by_key(ekey)
        if not p_name:
            return False
        low_n = p_name.lower()
        st = self.player_dead_state.get(low_n)
        changed = False
        if st and st.get("is_dead"):
            st["is_dead"] = False
            changed = True
        for p in self.players_combat.values():
            if p["name"].lower() == low_n or (p["is_local"] and self.player_identified and low_n == self.local_player_name.lower()):
                if p.get("is_dead"):
                    p["is_dead"] = False
                    changed = True
        return changed

    def _resolve_combatant(self, caster_key, sk_id):
        """
        Resolve com precisão cirúrgica quem é o autor do ataque (jogador local vs membro da party/raid),
        alinhado ao modelo de entidades do Questlog (combat.cjs A1 / k1).
        Garante que:
        1. Se outro membro atacar primeiro (ex: Tank/Glad puxando Boss), NÃO rouba a identidade do jogador local.
        2. Nenhum ataque de membro de grupo/raid é descartado por falta de mapeamento prévio de key.
        3. Associa a key dinâmica ao membro da raid pela classe da habilidade utilizada (ou provisoriamente se sk_id=0, refinando no primeiro hit de classe).
        4. O jogador local NUNCA é adivinhado por aproximação ou histórico de outros players.
        """
        # 0. Se o caster for um NPC registrado (e não o jogador local), NUNCA trata como jogador!
        if caster_key in self.npc_registry and caster_key != self.local_player_key:
            return None, False

        sk_class = get_class_by_skill_id(sk_id) if sk_id else None

        # 0.5. Refinamento de key provisória caso um membro tenha iniciado com ataque básico (sk_id=0)
        # e agora utilize uma skill de classe específica:
        if caster_key in self.provisional_keys and sk_class:
            cur_name = self.players_names.get(caster_key)
            cur_cls = None
            if cur_name and cur_name in self.party_members:
                cur_cls = self.party_members[cur_name].get("class")
            elif cur_name and self.player_identified and self.local_player_name and cur_name.lower() == self.local_player_name.lower():
                cur_cls = self.local_class
            if cur_cls == sk_class:
                self.provisional_keys.discard(caster_key)
            elif cur_cls and cur_cls != sk_class and self.party_members:
                for m_name, m_data in self.party_members.items():
                    if m_data.get("class") == sk_class and (not m_data.get("key") or m_data.get("key") in self.provisional_keys):
                        old_m_key = m_data.get("key")
                        if cur_name in self.party_members:
                            self.party_members[cur_name]["key"] = old_m_key if (old_m_key and old_m_key != caster_key) else 0
                            if self.party_members[cur_name]["key"]:
                                self.players_names[self.party_members[cur_name]["key"]] = cur_name
                        if self.local_player_key == caster_key:
                            self.local_player_key = None
                        m_data["key"] = caster_key
                        self.players_names[caster_key] = m_name
                        self.provisional_keys.discard(caster_key)
                        is_new_loc = bool(self.player_identified and self.local_player_name and m_name.lower() == self.local_player_name.lower())
                        if is_new_loc:
                            self.local_player_key = caster_key
                        for c_k, c_entry in list(self.players_combat.items()):
                            if c_entry.get("caster_key") == caster_key:
                                self.players_combat.pop(c_k, None)
                                new_k = "LOCAL" if is_new_loc else m_name
                                c_entry["name"]        = self.local_player_name if is_new_loc else m_name
                                c_entry["is_local"]    = is_new_loc
                                c_entry["class"]       = sk_class
                                c_entry["combatPower"] = self.local_combat_power if is_new_loc else (m_data.get("combatPower") or self.get_player_cp(m_name, caster_key))
                                if new_k in self.players_combat:
                                    self.players_combat[new_k]["damage"]       += c_entry["damage"]
                                    self.players_combat[new_k]["hits"]         += c_entry["hits"]
                                    self.players_combat[new_k]["overTimeHits"]  = self.players_combat[new_k].get("overTimeHits", 0) + c_entry.get("overTimeHits", 0)
                                    self.players_combat[new_k]["crits"]        += c_entry["crits"]
                                else:
                                    self.players_combat[new_k] = c_entry
                                break
                        break

        # 1. Já confirmado como jogador local?
        if self.local_player_key and caster_key == self.local_player_key:
            if not self.player_identified or self.local_player_name in (None, "", "Aguardando identificar jogador"):
                if self.local_dbid and self.local_dbid in self.players_by_dbid:
                    self.local_player_name = self.players_by_dbid[self.local_dbid]
                    self.player_identified = True
                if not self.player_identified and self.party_members:
                    unkeyed = [m for m, d in self.party_members.items() if not d.get("key") or d.get("key") == caster_key]
                    if len(unkeyed) == 1:
                        self.local_player_name = unkeyed[0]
                        self.player_identified = True
            return self.local_player_name, True

        # 2. Já mapeado em players_names?
        if caster_key in self.players_names:
            name = self.players_names[caster_key]
            is_loc = bool(self.player_identified and self.local_player_name and name.lower() == self.local_player_name.lower())
            if is_loc and not self.local_player_key:
                self.local_player_key = caster_key
            return name, is_loc

        # 3. Mapeado previamente em party_members com essa key?
        for m_name, m_data in self.party_members.items():
            if m_data.get("key") and m_data["key"] == caster_key:
                self.players_names[caster_key] = m_name
                is_loc = bool(self.player_identified and self.local_player_name and m_name.lower() == self.local_player_name.lower())
                if is_loc and not self.local_player_key:
                    self.local_player_key = caster_key
                return m_name, is_loc

        # 4. Se o jogador local ainda não tem local_player_key (ou se a key antiga ficou obsoleta e ele ainda não pontuou nesta luta):
        other_unkeyed_same_class = [
            m_name for m_name, m_data in self.party_members.items()
            if m_data.get("class") == self.local_class
            and (not m_data.get("key") or m_data.get("key") in self.provisional_keys)
            and (not self.player_identified or not self.local_player_name or m_name.lower() != self.local_player_name.lower())
        ]
        if self.local_class and sk_class and sk_class == self.local_class and (
            not self.local_player_key
            or ("LOCAL" not in self.players_combat and not other_unkeyed_same_class)
        ):
            self.local_player_key = caster_key
            self.provisional_keys.discard(caster_key)
            if not self.player_identified or self.local_player_name in (None, "", "Aguardando identificar jogador"):
                if self.local_dbid and self.local_dbid in self.players_by_dbid:
                    self.local_player_name = self.players_by_dbid[self.local_dbid]
                    self.player_identified = True
                elif self.party_members:
                    unkeyed = [m for m, d in self.party_members.items() if d.get("class") == self.local_class]
                    if len(unkeyed) == 1:
                        self.local_player_name = unkeyed[0]
                        self.player_identified = True
            if self.player_identified and self.local_player_name:
                self.players_names[caster_key] = self.local_player_name
                for m_name, m_data in self.party_members.items():
                    if m_name.lower() == self.local_player_name.lower():
                        m_data["key"] = caster_key
                        break
                log(f"[AutoID] Confirmado local_player_key={caster_key} para {self.local_player_name} via skill {sk_id} ({sk_class})")
                return self.local_player_name, True

        # 5. Associa a key a um membro da party/raid:
        if self.party_members:
            if sk_class:
                # 5a. Prioriza membros sem key (ou com key provisória) da mesma classe
                unkeyed_members = [
                    (m_name, m_data) for m_name, m_data in self.party_members.items()
                    if m_data.get("class") == sk_class and (not m_data.get("key") or m_data.get("key") in self.provisional_keys)
                    and (not self.local_player_key or not self.player_identified or not self.local_player_name or m_name.lower() != self.local_player_name.lower())
                ]
                # 5b. Se todos já tinham key antiga mas algum membro dessa classe ainda não pontuou nesta luta (ex: reconectou/mudou de key):
                if not unkeyed_members:
                    unkeyed_members = [
                        (m_name, m_data) for m_name, m_data in self.party_members.items()
                        if m_data.get("class") == sk_class
                        and m_name not in self.players_combat
                        and (not self.local_player_key or not self.player_identified or not self.local_player_name or m_name.lower() != self.local_player_name.lower())
                    ]
                if unkeyed_members:
                    matched_name, m_data = unkeyed_members[0]
                    m_data["key"] = caster_key
                    self.provisional_keys.discard(caster_key)
                    self.party_member_keys.add(caster_key)
                    self.players_names[caster_key] = matched_name
                    is_loc = bool(self.player_identified and self.local_player_name and matched_name.lower() == self.local_player_name.lower())
                    if is_loc and not self.local_player_key:
                        self.local_player_key = caster_key
                    log(f"[RaidID] Associado membro da raid {matched_name} ({sk_class}) -> Key={caster_key}")
                    return matched_name, is_loc
            else:
                # 5c. sk_class é None (ataque básico / auto-attack / Godstone / DoT)
                # Associa a um membro sem key (provisoriamente se houver >1 sem key, garantindo que NENHUM hit no Boss seja perdido!)
                unkeyed_non_local = [
                    (m_name, m_data) for m_name, m_data in self.party_members.items()
                    if not m_data.get("key")
                    and (not self.player_identified or not self.local_player_name or m_name.lower() != self.local_player_name.lower())
                ]
                unkeyed_all = [
                    (m_name, m_data) for m_name, m_data in self.party_members.items()
                    if not m_data.get("key")
                ]
                candidates = unkeyed_non_local if (self.local_player_key or unkeyed_non_local) else unkeyed_all
                if not candidates:
                    # Se todos tinham keys antigas de fora da instância, verifica quem ainda não pontuou nesta luta:
                    candidates = [
                        (m_name, m_data) for m_name, m_data in self.party_members.items()
                        if m_name not in self.players_combat
                        and (not self.player_identified or not self.local_player_name or m_name.lower() != self.local_player_name.lower() or "LOCAL" not in self.players_combat)
                    ]
                if candidates:
                    matched_name, m_data = candidates[0]
                    m_data["key"] = caster_key
                    if len(candidates) > 1 or len(unkeyed_all) > 1:
                        self.provisional_keys.add(caster_key)
                    self.party_member_keys.add(caster_key)
                    self.players_names[caster_key] = matched_name
                    is_loc = bool(self.player_identified and self.local_player_name and matched_name.lower() == self.local_player_name.lower())
                    if is_loc and not self.local_player_key:
                        self.local_player_key = caster_key
                    log(f"[RaidID] Associado membro sem key {matched_name} -> Key={caster_key}")
                    return matched_name, is_loc

        # 7. Se o jogador local ainda não foi identificado, NUNCA adivinha por combatentes próximos ou histórico.
        # Aguarda estritamente o teleporte ou login de personagem:
        if not self.player_identified:
            return None, False

        # 8. Se temos party_members ativa, combatentes que não pertencem ao grupo/raid são descartados!
        # NUNCA cria fantasmas ('Assassin', 'Gladiator') na party de quem não existe no grupo!
        if self.party_members:
            return None, False

        # 9. Fallback apenas se SOLO identificado:
        cand_name = f"{sk_class.capitalize()}" if sk_class else f"Player_{caster_key % 1000}"
        if cand_name in self.players_combat and self.players_combat[cand_name].get("caster_key", caster_key) != caster_key:
            cand_name = f"{sk_class.capitalize()}_{caster_key % 1000}" if sk_class else f"Player_{caster_key % 10000}"
        self.players_names[caster_key] = cand_name
        return cand_name, False

    def _prune_non_party_combatants(self):
        # Se a party só tiver o próprio jogador local (<= 1 membro externo), limpa a party para voltar a SOLO nas próximas lutas
        if self.player_identified:
            other_members = [
                m_name for m_name in self.party_members
                if m_name.lower() != self.local_player_name.lower()
            ]
            if not other_members:
                self.party_members.clear()

        # IMPORTANTE (Idêntico ao Questlog): NUNCA apaga de self.players_combat quem já bateu na luta atual/finalizada
        # quando os membros saem da party/dungeon após matar o Boss! O relatório da luta permanece intacto na tela!
        if self.in_combat and self.combat_start:
            dur = self._get_fight_duration()
            self._update_target_label(is_dead=self.target_is_dead, dur=dur)
            if self.view_mode == "SOLO":
                self.render_hud(dur)
            else:
                self.render_skills(dur)
        else:
            self.show_standby_local_player()

    def update_loop(self):
        now = time.time()
        needs_redraw = False

        # Atalho global F8 (VK_F8 = 0x77) para alternar modo Click-Through (Travar/Destravar HUD p/ Frame Gen)
        if sys.platform == "win32":
            try:
                f8_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x77) & 0x8000)
                if f8_down and not self._f8_was_down:
                    self.toggle_click_through()
                self._f8_was_down = f8_down
            except Exception:
                pass
        self._sync_hover_and_click_through()

        while not self.event_queue.empty():
            evt = self.event_queue.get_nowait()
            if self.is_paused:
                continue
            etype = evt.get("type")

            # 0. Sincronização de Relógio do Servidor (MapFrame_NT)
            if etype == "server_time":
                self.server_offset_ms = evt["server_time"] - evt["local_ms"]
                if self.active_target_berserk_ms > 0 and self.active_target_berserk_epoch is None:
                    self.active_target_berserk_epoch = self._compute_berserk_epoch(self.active_target_berserk_ms)
                    needs_redraw = True

            # 0.2. Personagens da Conta (Login_RS 13845)
            elif etype == "login_characters":
                self.account_characters = evt.get("characters", [])
                for c in self.account_characters:
                    c_name = c.get("name")
                    if c_name:
                        self._remember_player(c_name, c.get("class"), c.get("combatPower", 0), c.get("key", 0), c.get("dbid", 0), is_party_or_local=True)
                if self.in_combat or self.players_combat or self.combat_frozen or self.current_map_id is not None:
                    self._perform_map_or_loading_reset(new_map=None, new_map_key=0, clear_keys=True, set_loading=False, now=now, reset_map_id=True)

            # 0.5. Mudança de Mapa / Entrada ou Saída de Dungeon / Qualquer Loading (PrepareEnterMap_NT 13857)
            elif etype == "map_change":
                new_map = evt.get("map_id")
                # Reseta métricas SEMPRE em qualquer saída de dungeon, troca de mapa ou tela de loading (mesmo dentro do mesmo mapId)
                self._perform_map_or_loading_reset(new_map=new_map, new_map_key=0, clear_keys=True, set_loading=True, now=now)

            # 0.6. Status do Sniffer de Rede (TShark / Npcap)
            elif etype == "sniffer_status":
                s_stat = evt.get("status")
                if s_stat == "connected":
                    if not self.in_combat:
                        self.show_standby_local_player()
                elif s_stat in ("disconnected", "error"):
                    err_text = evt.get("error", "")
                    if "permission" in err_text.lower() or "admin" in err_text.lower():
                        self.active_target_name = "⚠️ Requer Admin (Npcap)"
                    else:
                        self.active_target_name = "⚠️ Sniffer Reconectando..."
                    if not self.in_combat:
                        self._update_target_label(is_dead=False, dur=0.0)

            # 1. Próprio Personagem Local (Identificado ao mudar de mapa / carregar / entrar ou sair de Dungeon)
            elif etype == "my_char":
                mc_map = evt.get("map_id") or 0
                mc_map_key = evt.get("map_key") or 0
                cur_map = getattr(self, "current_map_id", None)
                cur_map_key = getattr(self, "current_map_key", 0)
                cur_player_key = getattr(self, "local_player_key", None)

                map_changed = bool(mc_map > 0 and cur_map is not None and mc_map != cur_map)
                inst_changed = bool(mc_map_key != 0 and cur_map_key != 0 and mc_map_key != cur_map_key)
                has_old_combat = bool(self.in_combat or self.players_combat or self.combat_frozen)
                char_reloaded = bool(
                    has_old_combat
                    and (cur_player_key is not None or (now - getattr(self, "last_map_reset_t", 0.0) > 2.0))
                )

                self.is_loading = False
                if map_changed or inst_changed or char_reloaded:
                    self._perform_map_or_loading_reset(
                        new_map=mc_map if mc_map > 0 else cur_map,
                        new_map_key=mc_map_key,
                        clear_keys=True,
                        set_loading=False,
                        now=now
                    )
                else:
                    if mc_map > 0:
                        self.current_map_id = mc_map
                    if mc_map_key != 0:
                        self.current_map_key = mc_map_key

                self.local_player_key = evt["key"]
                self.provisional_keys.discard(self.local_player_key)
                self.npc_registry.pop(self.local_player_key, None)
                if evt.get("dbid"):
                    self.local_dbid = int(evt["dbid"])
                    self.dbid_to_key[self.local_dbid] = self.local_player_key
                if evt.get("class"):
                    self.local_class = evt["class"]
                if evt.get("combatPower", 0) > 0:
                    self.local_combat_power = evt["combatPower"]

                raw_nick = (evt.get("name") or "").strip()
                p_name = None
                if raw_nick and raw_nick != "Aguardando identificar jogador":
                    p_name = raw_nick
                elif self.local_dbid and self.local_dbid in self.players_by_dbid:
                    p_name = self.players_by_dbid[self.local_dbid]
                elif self.player_identified and self.local_player_name and self.local_player_name != "Aguardando identificar jogador":
                    p_name = self.local_player_name
                elif self.account_characters:
                    for ac in self.account_characters:
                        if self.local_dbid and ac.get("dbid") == self.local_dbid:
                            p_name = ac["name"]
                            break
                        if evt.get("pcId") and ac.get("pcId") == evt.get("pcId"):
                            p_name = ac["name"]
                            break
                        if ac.get("class") and ac.get("class") == self.local_class:
                            p_name = ac["name"]
                            break
                    if not p_name and len(self.account_characters) == 1:
                        p_name = self.account_characters[0]["name"]

                # Dedução inteligente caso o medidor tenha sido iniciado com o jogo já aberto:
                if not p_name and self.party_members:
                    if self.local_dbid:
                        for m_name, m_data in self.party_members.items():
                            if m_data.get("dbid") == self.local_dbid:
                                p_name = m_name
                                break
                    if not p_name:
                        matching_class_members = [
                            m_name for m_name, m_data in self.party_members.items()
                            if m_data.get("class") == self.local_class
                        ]
                        if len(matching_class_members) == 1:
                            p_name = matching_class_members[0]
                        elif len(matching_class_members) > 1 and self.local_combat_power > 0:
                            matching_class_members.sort(key=lambda m: abs(self.party_members[m].get("combatPower", 0) - self.local_combat_power))
                            p_name = matching_class_members[0]
                        elif not matching_class_members:
                            unkeyed = [
                                m_name for m_name, m_data in self.party_members.items()
                                if not m_data.get("key") or m_data.get("key") == self.local_player_key
                            ]
                            if len(unkeyed) == 1:
                                p_name = unkeyed[0]

                # Fallback estrito: apenas o último jogador local confirmado pelo usuário ou login (nunca estranhos do mundo)
                if not p_name:
                    last_lp = load_config().get("last_local_player")
                    if isinstance(last_lp, dict) and last_lp.get("name"):
                        if not self.local_class or last_lp.get("class") == self.local_class:
                            p_name = last_lp["name"]
                            if self.local_combat_power <= 0 and last_lp.get("combatPower", 0) > 0:
                                self.local_combat_power = int(last_lp["combatPower"])

                if p_name:
                    self.local_player_name = p_name
                    self.player_identified = True
                    self.players_names[self.local_player_key] = self.local_player_name

                    # Se já havia informações da party ou players_info, sincroniza CP/classe se disponível
                    for m_name, m_data in self.party_members.items():
                        if (
                            m_name.lower() == self.local_player_name.lower()
                            or (self.local_dbid and m_data.get("dbid") == self.local_dbid)
                            or (m_data.get("key") and m_data.get("key") == self.local_player_key)
                        ):
                            m_data["key"] = self.local_player_key
                            if self.local_dbid and not m_data.get("dbid"):
                                m_data["dbid"] = self.local_dbid
                            if m_data.get("class"):
                                self.local_class = m_data["class"]
                            if m_data.get("combatPower", 0) > 0 and self.local_combat_power <= 0:
                                self.local_combat_power = m_data["combatPower"]
                            break
                    if self.local_combat_power <= 0:
                        for p_n, p_inf in self.players_info.items():
                            if p_n.lower() == self.local_player_name.lower() and p_inf.get("combatPower", 0) > 0:
                                self.local_combat_power = p_inf["combatPower"]
                                break
                    self._remember_player(self.local_player_name, self.local_class, self.local_combat_power, self.local_player_key, self.local_dbid, is_party_or_local=True)
                    save_config({
                        "last_local_player": {
                            "name": self.local_player_name,
                            "class": self.local_class or "templar",
                            "combatPower": self.local_combat_power
                        }
                    })

                    if "LOCAL" in self.players_combat:
                        self.players_combat["LOCAL"]["name"]        = self.local_player_name
                        self.players_combat["LOCAL"]["class"]       = self.local_class
                        self.players_combat["LOCAL"]["combatPower"] = self.local_combat_power
                    if not self.in_combat:
                        self.show_standby_local_player()
                    else:
                        needs_redraw = True

            # 2. Outro Jogador (CharAppear_NT 13893 - Questlog w4)
            elif etype == "other_char":
                p_name = (evt.get("name") or "").strip()
                p_key  = evt["key"]
                p_dbid = int(evt.get("dbid") or 0)
                p_cls  = evt.get("class") or "gladiator"
                cp_v   = int(evt.get("combatPower") or 0)

                if p_key == self.local_player_key or (self.local_dbid and p_dbid == self.local_dbid):
                    continue

                self.npc_registry.pop(p_key, None)
                self.provisional_keys.discard(p_key)
                if p_dbid > 0:
                    self.dbid_to_key[p_dbid] = p_key
                    if not p_name and p_dbid in self.players_by_dbid:
                        p_name = self.players_by_dbid[p_dbid]

                # Se CharAppear_NT veio sem nickname ou com tag diferente, vincula pelo dbid da party!
                matched_party = False
                for m_name, m_data in self.party_members.items():
                    if (p_dbid > 0 and m_data.get("dbid") == p_dbid) or (p_name and m_name.lower() == p_name.lower()):
                        matched_party = True
                        if not p_name:
                            p_name = m_name
                        m_data["key"] = p_key
                        if p_dbid > 0:
                            m_data["dbid"] = p_dbid
                        if p_cls:
                            m_data["class"] = p_cls
                        if cp_v > 0:
                            m_data["combatPower"] = cp_v
                            if m_name in self.players_combat:
                                self.players_combat[m_name]["combatPower"] = cp_v
                                needs_redraw = True
                        self.party_member_keys.add(p_key)
                        break

                if not p_name and p_key in self.players_names:
                    p_name = self.players_names[p_key]

                self.key_to_char[p_key] = {
                    "dbid":        p_dbid,
                    "name":        p_name,
                    "class":       p_cls,
                    "combatPower": cp_v
                }

                if not p_name:
                    continue

                if len(self.players_names) > 1000:
                    party_keys = {m_data.get("key"): m_name for m_name, m_data in self.party_members.items() if m_data.get("key")}
                    self.players_names.clear()
                    self.players_names.update(party_keys)
                self.players_names[p_key] = p_name

                # Memoriza classe, CP, key e dbid (apenas persiste no config se for membro do grupo ou jogador local)
                is_part = bool(matched_party or p_key in self.party_member_keys or (self.local_player_name and p_name.lower() == self.local_player_name.lower()))
                self._remember_player(p_name, p_cls, cp_v, p_key, p_dbid, is_party_or_local=is_part)

                if not matched_party and p_key in self.party_member_keys:
                    self.party_members[p_name] = {
                        "key":         p_key,
                        "dbid":        p_dbid,
                        "class":       p_cls or "gladiator",
                        "combatPower": cp_v or self.get_player_cp(p_name, p_key),
                        "deaths":      0
                    }

                # Se esse combatente já estava registrado com seu nome, atualiza CP e classe imediatamente
                if p_name in self.players_combat:
                    if p_cls: self.players_combat[p_name]["class"] = p_cls
                    if cp_v > 0:
                        self.players_combat[p_name]["combatPower"] = cp_v
                        needs_redraw = True

                # Se esse combatente estava registrado em players_combat com chave provisória, renomeia/mescla:
                for c_k, c_data in list(self.players_combat.items()):
                    if c_k != "LOCAL" and c_data.get("caster_key") == p_key and c_k != p_name:
                        entry = self.players_combat.pop(c_k)
                        entry["name"] = p_name
                        if p_cls: entry["class"] = p_cls
                        if cp_v > 0: entry["combatPower"] = cp_v
                        if p_name in self.players_combat:
                            self.players_combat[p_name]["damage"]       += entry["damage"]
                            self.players_combat[p_name]["hits"]         += entry["hits"]
                            self.players_combat[p_name]["overTimeHits"]  = self.players_combat[p_name].get("overTimeHits", 0) + entry.get("overTimeHits", 0)
                            self.players_combat[p_name]["crits"]        += entry["crits"]
                        else:
                            self.players_combat[p_name] = entry
                        needs_redraw = True
                        break

            # 3. Combat Power Local (CharCombatPowerUpdate_NT 13910)
            elif etype == "local_cp":
                cp_v = evt.get("combatPower", 0)
                if cp_v > 0:
                    self.local_combat_power = cp_v
                    if self.player_identified and self.local_player_name and self.local_player_name != "Aguardando identificar jogador":
                        self._remember_player(self.local_player_name, self.local_class, self.local_combat_power, self.local_player_key, self.local_dbid, is_party_or_local=True)
                        save_config({
                            "last_local_player": {
                                "name": self.local_player_name,
                                "class": self.local_class or "templar",
                                "combatPower": self.local_combat_power
                            }
                        })
                    if "LOCAL" in self.players_combat:
                        self.players_combat["LOCAL"]["combatPower"] = self.local_combat_power
                    if self.player_identified and not self.in_combat:
                        self.show_standby_local_player()
                    elif self.in_combat:
                        needs_redraw = True

            # 4. Informações de Grupo (PartyInfo_NT / ForceInfo_NT)
            elif etype == "party_info":
                prev_keys = {m_name.lower(): m_data.get("key", 0) for m_name, m_data in self.party_members.items() if m_data.get("key")}
                for k_id, k_name in self.players_names.items():
                    if k_id and k_name:
                        prev_keys[k_name.lower()] = k_id
                self.party_members.clear()
                for m in evt["members"]:
                    m_name = m["name"]
                    m_dbid = int(m.get("dbid") or 0)
                    m_cp   = int(m.get("combatPower") or 0)
                    m_key  = m.get("key") or (self.dbid_to_key.get(m_dbid, 0) if m_dbid else 0) or prev_keys.get(m_name.lower(), 0)
                    if m_key and m_key in self.key_to_char and m_cp <= 0:
                        m_cp = self.key_to_char[m_key].get("combatPower", 0)
                    if m_key:
                        self.players_names[m_key] = m_name
                        self.npc_registry.pop(m_key, None)
                        self.provisional_keys.discard(m_key)
                    self._remember_player(m_name, m.get("class"), m_cp, m_key, m_dbid, is_party_or_local=True)
                    self.party_members[m_name] = {
                        "key":         m_key,
                        "dbid":        m_dbid,
                        "class":       m["class"],
                        "combatPower": m_cp or self.get_player_cp(m_name, m_key),
                        "deaths":      0
                    }
                    is_loc_member = bool(
                        (self.local_dbid and m_dbid == self.local_dbid)
                        or (self.player_identified and self.local_player_name and m_name.lower() == self.local_player_name.lower())
                        or (self.local_player_key and m_key and m_key == self.local_player_key)
                    )
                    if is_loc_member:
                        if m_name and m_name != "Aguardando identificar jogador":
                            self.local_player_name = m_name
                            self.player_identified = True
                        if m_key and not self.local_player_key:
                            self.local_player_key = m_key
                        if m_dbid and not self.local_dbid:
                            self.local_dbid = m_dbid
                        if m.get("class"):
                            self.local_class = m["class"]
                        if m_cp > 0:
                            self.local_combat_power = m_cp
                            save_known_char(self.local_player_name, self.local_class, self.local_combat_power)
                            save_config({
                                "last_local_player": {
                                    "name": self.local_player_name,
                                    "class": self.local_class or "templar",
                                    "combatPower": self.local_combat_power
                                }
                            })
                        if "LOCAL" in self.players_combat:
                            self.players_combat["LOCAL"]["name"]        = self.local_player_name
                            self.players_combat["LOCAL"]["class"]       = self.local_class
                            self.players_combat["LOCAL"]["combatPower"] = self.local_combat_power
                    else:
                        if m_key:
                            self.party_member_keys.add(m_key)
                        if m_name in self.players_combat and m_cp > 0:
                            self.players_combat[m_name]["combatPower"] = m_cp
                self._prune_non_party_combatants()

            # 4.5. Informações de Party Finder / Matchmaking (PartyFinderGroup_NT 38658)
            elif etype == "party_finder_info":
                for m in evt["members"]:
                    m_name = m["name"]
                    m_dbid = int(m.get("dbid") or 0)
                    m_cp   = int(m.get("combatPower") or 0)
                    m_cls  = m.get("class") or "gladiator"
                    existing = self.party_members.get(m_name, {})
                    m_key  = existing.get("key") or (self.dbid_to_key.get(m_dbid, 0) if m_dbid else 0)
                    if m_key:
                        self.players_names[m_key] = m_name
                        self.npc_registry.pop(m_key, None)
                    self._remember_player(m_name, m_cls, m_cp, m_key, m_dbid, is_party_or_local=True)
                    self.party_members[m_name] = {
                        "key":         m_key,
                        "dbid":        m_dbid or existing.get("dbid", 0),
                        "class":       m_cls,
                        "combatPower": m_cp or existing.get("combatPower", 0) or self.get_player_cp(m_name, m_key),
                        "deaths":      existing.get("deaths", 0)
                    }

            # 5. Membro Adicionado ou Reconectado ao Grupo (PartyAddMember_NT / PartyReconnectMember_NT / ForceAdd / ForceReconnect)
            elif etype == "party_add":
                m = evt["member"]
                m_name = m["name"]
                m_dbid = int(m.get("dbid") or 0)
                m_cp   = int(m.get("combatPower") or 0)
                m_key  = m.get("key", 0) or (self.dbid_to_key.get(m_dbid, 0) if m_dbid else 0)
                if not m_key:
                    for k_id, k_name in self.players_names.items():
                        if k_name and k_name.lower() == m_name.lower():
                            m_key = k_id
                            break
                if m_key and m_key in self.key_to_char and m_cp <= 0:
                    m_cp = self.key_to_char[m_key].get("combatPower", 0)
                if m_key:
                    self.players_names[m_key] = m_name
                    self.npc_registry.pop(m_key, None)
                    self.provisional_keys.discard(m_key)
                self._remember_player(m_name, m.get("class"), m_cp, m_key, m_dbid, is_party_or_local=True)
                self.party_members[m_name] = {
                    "key":         m_key,
                    "dbid":        m_dbid,
                    "class":       m["class"],
                    "combatPower": m_cp or self.get_player_cp(m_name, m_key),
                    "deaths":      0
                }
                is_loc_member = bool(
                    (self.local_dbid and m_dbid == self.local_dbid)
                    or (self.player_identified and m_name.lower() == self.local_player_name.lower())
                )
                if is_loc_member and m_key:
                    self.local_player_key = m_key
                elif m_key:
                    self.party_member_keys.add(m_key)
                if m_name in self.players_combat and m_cp > 0:
                    self.players_combat[m_name]["combatPower"] = m_cp
                    needs_redraw = True

            # 5.8. Confirmação de Membro da Party em Tempo Real (PartyUpdateMemberHPMP_NT / ForceUpdateMemberHPMP_NT)
            elif etype == "party_hpmp":
                m_key = evt.get("key", 0)
                hp_v  = evt.get("hp")
                live  = evt.get("live", True)
                if m_key:
                    if m_key != self.local_player_key:
                        self.party_member_keys.add(m_key)
                        p_name = self.players_names.get(m_key)
                        if p_name and (not self.player_identified or p_name.lower() != self.local_player_name.lower()):
                            already = any(mn.lower() == p_name.lower() for mn in self.party_members)
                            if not already:
                                p_inf = self.players_info.get(p_name, {})
                                self.party_members[p_name] = {
                                    "key":         m_key,
                                    "dbid":        0,
                                    "class":       p_inf.get("class", "gladiator"),
                                    "combatPower": p_inf.get("combatPower", 0),
                                    "deaths":      0
                                }
                    if not live or (hp_v is not None and hp_v <= 0):
                        if self._mark_player_dead(m_key, now):
                            needs_redraw = True
                    elif live and hp_v is not None and hp_v > 0:
                        if self._mark_player_alive(m_key):
                            needs_redraw = True

            # 6. Atualização de Status do Membro
            elif etype == "party_update":
                cp_v = evt.get("combatPower", 0)
                if cp_v > 0:
                    matched = False
                    for m_name, m_data in self.party_members.items():
                        if m_data.get("dbid") and m_data["dbid"] == evt["dbid"]:
                            matched = True
                            m_data["combatPower"] = cp_v
                            self._remember_player(m_name, cp=cp_v, dbid=evt["dbid"], is_party_or_local=True)
                            if self.player_identified and m_name.lower() == self.local_player_name.lower():
                                self.local_combat_power = cp_v
                                if "LOCAL" in self.players_combat:
                                    self.players_combat["LOCAL"]["combatPower"] = cp_v
                                needs_redraw = True
                            elif m_name in self.players_combat:
                                self.players_combat[m_name]["combatPower"] = cp_v
                                needs_redraw = True
                            break
                    if not matched:
                        p_cls = get_class_by_pcid(evt.get("pcId", 0))
                        for m_name, m_data in self.party_members.items():
                            if m_data.get("class") == p_cls and m_data.get("combatPower", 0) == 0:
                                m_data["dbid"] = evt["dbid"]
                                m_data["combatPower"] = cp_v
                                self._remember_player(m_name, p_cls, cp=cp_v, dbid=evt["dbid"], is_party_or_local=True)
                                if m_name in self.players_combat:
                                    self.players_combat[m_name]["combatPower"] = cp_v
                                    needs_redraw = True
                                break

            # 6.5. Membro Removido por DBID (ForceRemoveMember_NT)
            elif etype == "party_remove_dbid":
                rem_dbid = evt.get("dbid")
                to_del = [m_name for m_name, m_data in self.party_members.items() if m_data.get("dbid") == rem_dbid]
                for m_name in to_del:
                    rem_k = self.party_members[m_name].get("key")
                    if rem_k:
                        self.party_member_keys.discard(rem_k)
                    del self.party_members[m_name]
                self._prune_non_party_combatants()

            # 7. Saída / Desmanche / Kick do Grupo
            elif etype == "party_left":
                self.party_members.clear()
                self.party_member_keys.clear()
                self._prune_non_party_combatants()

            # 8. Monstro ou Summon/Totem Spawna (NpcAppear_NT 13889)
            elif etype == "npc_spawn":
                parent_key = evt.get("parent_key", 0)
                if parent_key > 0:
                    # É um Summon / Totem / Espírito / Pet de jogador! Mapeia para o dono (ownerOf no Questlog)
                    if len(self.summon_owners) > 1000:
                        self.summon_owners.clear()
                    self.summon_owners[evt["key"]] = parent_key
                    continue

                # Nunca registra um jogador como NPC (idêntico a if (t.has(g.entity)) break; do Questlog)
                if evt["key"] == self.local_player_key or evt["key"] in self.players_names or evt["key"] in self.party_member_keys:
                    continue

                # Capacidade de 4096 NPCs (idêntica a ei = 4096 no Questlog combat.cjs), preservando todos os Bosses!
                if len(self.npc_registry) >= 4096:
                    for old_k, old_v in list(self.npc_registry.items()):
                        if not old_v.get("is_boss") and old_k != self.active_target_key and old_k != self.active_boss_key:
                            del self.npc_registry[old_k]
                            if len(self.npc_registry) < 3500:
                                break

                b_ms = evt.get("berserk_ms", 0)
                is_b = evt.get("is_boss", False) or (b_ms > 0) or is_real_boss_npc(evt.get("npc_id", 0), evt.get("name", ""), self.current_map_id)
                self.npc_registry[evt["key"]] = {
                    "name":       evt["name"],
                    "npc_id":     evt["npc_id"],
                    "is_boss":    is_b,
                    "hp":         evt["hp"],
                    "hp_max":     evt["hp_max"],
                    "berserk_ms": b_ms,
                    "in_combat":  (b_ms > 0)
                }
                if evt["key"] == self.active_target_key:
                    if evt.get("name"):
                        self.active_target_name = evt["name"]
                    self.active_target_cur_hp = evt["hp"]
                    if evt["hp_max"] > 0:
                        self.active_target_max_hp = evt["hp_max"]
                    if b_ms > 0:
                        self.active_target_berserk_ms    = b_ms
                        self.active_target_berserk_epoch = self._compute_berserk_epoch(b_ms)
                    needs_redraw = True

            # 8.1. Alvo de Boss Oficial da Party (PartySetTargetByBoss_NT 37408) & Boss Intermediário Morto (22318)
            elif etype == "boss_target":
                b_key = evt.get("target_key", 0)
                if b_key and b_key != self.local_player_key and b_key not in self.players_names and b_key not in self.party_member_keys:
                    if b_key not in self.npc_registry:
                        self.npc_registry[b_key] = {
                            "name":       "",
                            "npc_id":     0,
                            "is_boss":    True,
                            "hp":         None,
                            "hp_max":     0,
                            "berserk_ms": 0,
                            "in_combat":  True
                        }
                    else:
                        self.npc_registry[b_key]["is_boss"] = True
            elif etype == "dungeon_boss_killed":
                b_npc_id = evt.get("npc_id", 0)
                b_name = get_boss_name(b_npc_id)
                if b_name:
                    self.killed_boss_names.add(b_name)

            # 8.2. Atualização de HP Real do Servidor (CharPointUpdate_NT 36096)
            elif etype == "hp_update":
                ekey = evt["key"]
                hp_v = evt.get("hp")
                hm_v = evt.get("hp_max")

                # Verifica se é um jogador (morte ou ressurreição em combate - Questlog XA)
                if ekey == self.local_player_key or ekey in self.players_names or ekey in self.party_member_keys:
                    if hp_v is not None:
                        if hp_v <= 0:
                            if self._mark_player_dead(ekey, now):
                                needs_redraw = True
                        else:
                            if self._mark_player_alive(ekey):
                                needs_redraw = True
                    continue

                if ekey not in self.npc_registry:
                    self.npc_registry[ekey] = {
                        "name":       "",
                        "npc_id":     0,
                        "is_boss":    bool((hm_v or 0) >= 5_000_000 or (hp_v or 0) >= 5_000_000),
                        "hp":         hp_v,
                        "hp_max":     hm_v or (hp_v or 0),
                        "berserk_ms": 0,
                        "in_combat":  True
                    }
                else:
                    if hp_v is not None:
                        self.npc_registry[ekey]["hp"] = hp_v
                    if hm_v is not None and hm_v > 0:
                        self.npc_registry[ekey]["hp_max"] = hm_v
                    elif hp_v is not None and hp_v > 0:
                        dealt_so_far = self.encounter_targets.get(ekey, 0)
                        if (self.npc_registry[ekey].get("hp_max") or 0) < (hp_v + dealt_so_far):
                            self.npc_registry[ekey]["hp_max"] = hp_v + dealt_so_far
                    if (self.npc_registry[ekey].get("hp_max") or 0) >= 5_000_000:
                        self.npc_registry[ekey]["is_boss"] = True

                if ekey == self.active_target_key or ekey == self.active_boss_key:
                    if hm_v is not None and hm_v > 0:
                        self.active_target_max_hp = hm_v
                    elif hp_v is not None and hp_v > 0:
                        dealt_so_far = self.encounter_targets.get(ekey, 0)
                        self.active_target_max_hp = max(self.active_target_max_hp or 0, hp_v + dealt_so_far)
                    if hp_v is not None:
                        self.active_target_cur_hp = hp_v
                        if hp_v <= 0 and self.in_combat:
                            if not self.encounter_has_boss or ekey == self.active_boss_key:
                                self.target_is_dead       = True
                                self.combat_frozen        = True
                                self.active_target_cur_hp = 0
                                if self.active_target_name and self.active_target_name not in ("Monstro", "Chefe", "Nenhum alvo"):
                                    self.killed_boss_names.add(self.active_target_name)
                    needs_redraw = True

            # 8.5. Estado de Combate do Boss / Enrage Timer Oficial (CombatStateUpdate_NT 36129)
            elif etype == "combat_state":
                ekey = evt["key"]
                b_ms = evt.get("berserk_ms", 0)
                if ekey != self.local_player_key and ekey not in self.players_names and ekey not in self.party_member_keys:
                    if ekey not in self.npc_registry:
                        self.npc_registry[ekey] = {
                            "name":       "",
                            "npc_id":     0,
                            "is_boss":    (b_ms > 0),
                            "hp":         None,
                            "hp_max":     0,
                            "berserk_ms": b_ms if evt["in_combat"] else 0,
                            "in_combat":  evt["in_combat"]
                        }
                    else:
                        self.npc_registry[ekey]["in_combat"]  = evt["in_combat"]
                        self.npc_registry[ekey]["berserk_ms"] = b_ms if evt["in_combat"] else 0
                        if b_ms > 0:
                            self.npc_registry[ekey]["is_boss"] = True
                if ekey == self.active_target_key or ekey == self.active_boss_key:
                    if evt["in_combat"] and b_ms > 0:
                        self.active_target_berserk_ms    = b_ms
                        self.active_target_berserk_epoch = self._compute_berserk_epoch(b_ms)
                    elif not evt["in_combat"]:
                        self.active_target_berserk_ms    = 0
                        self.active_target_berserk_epoch = None
                    needs_redraw = True

            # 9. Troca de Alvo do Jogador
            elif etype == "target_change":
                c_key = evt.get("caster_key")
                if c_key is None or c_key == self.local_player_key or self.local_player_key is None:
                    t_key = evt["target_key"]
                    if t_key != self.active_target_key:
                        npc = self.npc_registry.get(t_key)
                        # APENAS atualiza o preview antes de entrar em combate!
                        # NUNCA altera target_is_dead, combat_frozen ou active_target_name com uma luta ativa/finalizada!
                        if npc and not self.in_combat:
                            self.active_target_key           = t_key
                            self.active_target_name          = npc["name"]
                            self.active_target_cur_hp        = npc.get("hp")
                            self.active_target_max_hp        = npc["hp_max"]
                            self.active_target_berserk_ms    = npc.get("berserk_ms", 0)
                            self.active_target_berserk_epoch = self._compute_berserk_epoch(self.active_target_berserk_ms)
                            needs_redraw = True

            # 10. Dano Causado (Alinhado 100% com N(S) e j(S,z) do Questlog combat.cjs)
            elif etype == "damage":
                if getattr(self, "is_loading", False):
                    if (now - getattr(self, "loading_started_at", 0.0)) < 12.0:
                        continue
                    self.is_loading = False
                raw_caster = evt["caster_key"]
                # 10.0 Resolve Summon / Totem / Pet para o dono real (ownerOf no Questlog)
                caster_key = self.summon_owners.get(raw_caster, raw_caster)
                target_key = evt["target_key"]
                dmg        = evt["damage"]
                sk_id      = evt["skill_id"]
                is_crit    = evt["is_crit"]
                over_time  = evt.get("over_time", False)
                hit_t      = evt["time"]

                # 10.1 Se o alvo for player ou summon de player (dano recebido ou cura/buff), ignora
                if target_key == self.local_player_key or target_key in self.players_names or target_key in self.summon_owners:
                    continue

                # Se o atacante for um NPC/Monstro (e não o jogador local), NUNCA trata como dano de jogador!
                if caster_key in self.npc_registry and caster_key != self.local_player_key:
                    continue

                # 10.2 Resolve quem é o atacante com precisão cirúrgica (evita roubo de identidade)
                p_name, is_local = self._resolve_combatant(caster_key, sk_id)
                if not p_name:
                    continue

                # 10.3 FILTRO SOLO vs GRUPO / RAID:
                # - Se estiver SOLO (sem party): apenas o jogador local pontua.
                # - Se estiver em GRUPO / RAID: o jogador local e todos os membros da raid pontuam.
                if not is_local:
                    if not self.party_members:
                        continue
                    # Se temos party/raid ativa, verifica se o combatente pertence à party/raid ou se é um combatente da raid
                    in_party = (
                        (p_name in self.party_members)
                        or any(m_name.lower() == p_name.lower() for m_name in self.party_members)
                        or (caster_key in self.party_member_keys)
                        or any(m.get("key") == caster_key for m in self.party_members.values())
                    )
                    if not in_party:
                        continue

                # 10.5 Controle de Luta Congelada / Início e Reset de Encontro (Idêntico ao Questlog combat.cjs k1)
                is_dungeon = bool(self.current_map_id and (self.current_map_id in DUNGEON_BOSSES or self.current_map_id >= 600000))
                if target_key not in self.npc_registry:
                    self.npc_registry[target_key] = {
                        "name": "Chefe" if is_dungeon else "Monstro",
                        "npc_id": 0,
                        "is_boss": is_dungeon,
                        "hp": None,
                        "hp_max": 0,
                        "berserk_ms": 0,
                        "in_combat": True
                    }
                target_npc = self.npc_registry.get(target_key)
                target_is_boss = bool(
                    (target_npc and (target_npc.get("is_boss") or is_real_boss_npc(target_npc.get("npc_id", 0), target_npc.get("name", ""), self.current_map_id)))
                    or target_key in self.encounter_boss_keys
                    or target_key == self.active_boss_key
                    or is_dungeon
                )
                if not target_is_boss and target_npc and target_npc.get("berserk_ms", 0) > 0:
                    target_is_boss = True
                    target_npc["is_boss"] = True

                # SE O MODO "SÓ BOSS" ESTIVER ATIVO:
                if self.boss_only:
                    # Se não estamos em luta de boss ativa e o alvo NÃO é um Boss:
                    # Ignora completamente mobs comuns/trash mobs para não poluir o medidor
                    if not self.encounter_has_boss and not target_is_boss:
                        continue
                    # Se a luta anterior de Boss já foi finalizada (boss morreu ou congelado) e o alvo NÃO é boss:
                    # Mantém o relatório do Boss na tela, ignorando adds residuais ou trash a caminho do próximo boss
                    if (self.combat_frozen or self.target_is_dead) and not target_is_boss:
                        continue

                # Quando não há luta ativa ou a luta anterior já terminou (Boss morreu / Wipe congelado):
                # Ignora ticks residuais de DoT, hits <= 10 (Questlog eN = 10), hits no próprio alvo morto,
                # ou cleave em adds nos primeiros 3s após matar o Boss (para NUNCA apagar o relatório do Boss!).
                if not self.in_combat or self.combat_frozen or self.target_is_dead:
                    if over_time or dmg <= 10:
                        continue
                    if self.target_is_dead and target_key == self.active_target_key:
                        continue
                    if target_npc and target_npc.get("hp") is not None and target_npc.get("hp") <= 0 and target_key in self.encounter_targets:
                        continue
                    if (self.combat_frozen or self.target_is_dead) and self.encounter_has_boss and not target_is_boss:
                        if self.last_hit_t and (hit_t - self.last_hit_t) < 3.0:
                            continue

                idle_timeout = 90.0 if (self.encounter_has_boss or target_is_boss) else 15.0

                new_encounter = False
                if not self.in_combat:
                    new_encounter = True
                elif self.combat_frozen or self.target_is_dead:
                    # Luta anterior já estava encerrada/congelada (morte do boss/mob ou wipe) e um novo alvo vivo foi atacado
                    if not self.boss_only or target_is_boss:
                        new_encounter = True
                elif self.last_hit_t and (hit_t - self.last_hit_t) > idle_timeout:
                    # Inatividade prolongada (15s trash / 90s boss): fecha encontro anterior e abre novo
                    if not self.boss_only or target_is_boss:
                        new_encounter = True
                elif target_is_boss and not self.encounter_has_boss:
                    # Transição de trash para Boss: fecha a luta de trash e inicia o Boss isolado
                    new_encounter = True
                elif target_is_boss and self.active_boss_key and target_key != self.active_boss_key:
                    # Transição de um Boss A para um Boss B diferente (apenas se Boss A morreu ou ficou inativo > 12s)
                    prev_boss = self.npc_registry.get(self.active_boss_key)
                    if not prev_boss or prev_boss.get("hp", 1) <= 0 or not prev_boss.get("in_combat", True) or (self.last_hit_t and (hit_t - self.last_hit_t) > 12.0):
                        new_encounter = True

                if new_encounter:
                    self.in_combat           = True
                    self.combat_start        = hit_t
                    self.players_combat.clear()
                    self.player_dead_state.clear()
                    self.encounter_targets   = {}
                    self.encounter_has_boss  = target_is_boss
                    self.encounter_boss_keys = {target_key} if target_is_boss else set()
                    self.active_boss_key     = target_key if target_is_boss else None
                    self.target_is_dead      = False
                    self.combat_frozen       = False
                    self.active_target_key   = target_key
                    t_name = (target_npc.get("name") if target_npc else None) or (get_boss_name(target_npc.get("npc_id", 0)) if target_npc else None)
                    if not t_name:
                        t_name = "Chefe" if target_is_boss else "Monstro"
                    self.active_target_name          = t_name
                    self.active_target_cur_hp        = target_npc.get("hp") if target_npc else None
                    self.active_target_max_hp        = (target_npc.get("hp_max") if target_npc else 0) or 0
                    self.active_target_berserk_ms    = target_npc.get("berserk_ms", 0) if target_npc else 0
                    self.active_target_berserk_epoch = self._compute_berserk_epoch(self.active_target_berserk_ms)

                # Se o jogador causou dano direto (não-DoT) durante a luta ativa, garante que não está marcado como morto
                if not over_time:
                    self._mark_player_alive(caster_key)

                if target_is_boss:
                    self.encounter_has_boss = True
                    self.encounter_boss_keys.add(target_key)
                    if not self.active_boss_key or self.active_boss_key == target_key:
                        self.active_boss_key = target_key

                self.encounter_targets[target_key] = self.encounter_targets.get(target_key, 0) + dmg

                # Subtrai o dano do HP atual do monstro apenas se mantiver HP > 0 (a morte/HP=0 vem de CharPointUpdate_NT ou CharDie_NT)
                if target_npc and target_npc.get("hp") is not None and target_npc["hp"] > dmg:
                    target_npc["hp"] = target_npc["hp"] - dmg

                # Atualiza o alvo principal exibido no cabeçalho do HUD (Questlog tP):
                # Se houver boss na luta, o foco permanece estritamente no Boss ativo (ignora adds/totens no cabeçalho)
                if self.encounter_has_boss and self.active_boss_key:
                    main_key = self.active_boss_key
                else:
                    main_key = max(self.encounter_targets.items(), key=lambda kv: kv[1])[0]

                self.active_target_key = main_key
                main_npc = self.npc_registry.get(main_key)
                if main_npc:
                    if main_npc.get("name"):
                        self.active_target_name = main_npc["name"]
                    self.active_target_cur_hp = main_npc.get("hp")
                    if main_npc.get("hp_max"):
                        self.active_target_max_hp = main_npc["hp_max"]
                    if main_npc.get("berserk_ms"):
                        self.active_target_berserk_ms    = main_npc["berserk_ms"]
                        self.active_target_berserk_epoch = self._compute_berserk_epoch(self.active_target_berserk_ms)

                self.last_hit_t = hit_t

                # 10.7 Classe e Combat Power do Jogador
                p_class = self.local_class if is_local else (
                    self.party_members.get(p_name, {}).get("class")
                    or self.players_info.get(p_name, {}).get("class")
                )
                if not p_class:
                    p_class = get_class_by_skill_id(sk_id) or "gladiator"

                p_cp = self.get_player_cp(p_name, caster_key, is_local)

                # 10.8 Registra dano (Idêntico a v0(e, t) do Questlog: DoT soma damage e overTimeHits, sem diluir hits/critRate)
                key = "LOCAL" if is_local else p_name
                st_dead = self.player_dead_state.get(p_name.lower(), {})
                if key not in self.players_combat:
                    self.players_combat[key] = {
                        "name":          p_name,
                        "caster_key":    caster_key,
                        "is_local":      is_local,
                        "class":         p_class,
                        "combatPower":   p_cp,
                        "damage":        0,
                        "hits":          0,
                        "overTimeHits":  0,
                        "crits":         0,
                        "misses":        0,
                        "deaths":        st_dead.get("deaths", 0),
                        "is_dead":       st_dead.get("is_dead", False),
                        "skills":        {}
                    }

                p = self.players_combat[key]
                if p_cp > 0 and p.get("combatPower", 0) == 0:
                    p["combatPower"] = p_cp
                p["deaths"]  = st_dead.get("deaths", p.get("deaths", 0))
                p["is_dead"] = st_dead.get("is_dead", p.get("is_dead", False))
                p["damage"] += dmg
                if over_time:
                    p["overTimeHits"] += 1
                else:
                    p["hits"] += 1
                    if is_crit:
                        p["crits"] += 1

                # 10.9 Registra na habilidade (jogador local)
                if is_local:
                    if sk_id not in p["skills"]:
                        sk_name, sk_icon = get_skill_info(sk_id)
                        p["skills"][sk_id] = {
                            "name": sk_name,
                            "icon": sk_icon,
                            "damage": 0, "hits": 0, "overTimeHits": 0, "crits": 0, "max": 0
                        }
                    sk = p["skills"][sk_id]
                    sk["damage"] += dmg
                    if over_time:
                        sk["overTimeHits"] += 1
                    else:
                        sk["hits"] += 1
                        if is_crit:
                            sk["crits"] += 1
                        if dmg > sk["max"]:
                            sk["max"] = dmg

                needs_redraw = True

            # 11. Morte de Jogador ou Monstro / Despawn (Questlog case "death" - CharDie_NT 36100 / NpcDisappear_NT 13890)
            elif etype == "death":
                dead_key   = evt["dead_key"]
                is_despawn = evt.get("is_despawn", False)
                if dead_key in self.summon_owners:
                    del self.summon_owners[dead_key]

                # Se for a morte real (CharDie_NT 36100) de um jogador do grupo ou local:
                if not is_despawn and (dead_key == self.local_player_key or dead_key in self.players_names or dead_key in self.party_member_keys):
                    if self._mark_player_dead(dead_key, now):
                        needs_redraw = True
                    continue

                dead_npc = self.npc_registry.get(dead_key)
                dead_is_boss = bool(
                    (dead_npc and (dead_npc.get("is_boss") or is_real_boss_npc(dead_npc.get("npc_id", 0), dead_npc.get("name", ""), self.current_map_id)))
                    or dead_key == self.active_boss_key
                    or dead_key in getattr(self, "encounter_boss_keys", ())
                )

                if self.encounter_has_boss:
                    # Durante um encontro de Boss, APENAS a morte do Boss principal encerra a luta!
                    if dead_is_boss and dead_key == self.active_boss_key:
                        if dead_npc:
                            dead_npc["hp"]        = 0
                            dead_npc["in_combat"] = False
                        self.target_is_dead       = True
                        self.combat_frozen        = True
                        self.active_target_cur_hp = 0
                        if self.active_target_name and self.active_target_name not in ("Monstro", "Chefe", "Nenhum alvo"):
                            self.killed_boss_names.add(self.active_target_name)
                        needs_redraw = True
                    elif dead_key in self.npc_registry:
                        # Morte de um add / lacaio / spider durante a luta de boss:
                        # APENAS zera o HP do add. NUNCA congela ou encerra a luta do Boss!
                        self.npc_registry[dead_key]["hp"] = 0
                elif not self.boss_only and dead_key == self.active_target_key:
                    # Em modo normal (fora de boss_only), mob trash comum morreu:
                    if dead_npc:
                        dead_npc["hp"]        = 0
                        dead_npc["in_combat"] = False
                    self.target_is_dead       = True
                    self.combat_frozen        = True
                    self.active_target_cur_hp = 0
                    needs_redraw = True

        # Salva config.json no disco com debouncing (apenas fora de combate e quando houver alterações)
        if not self.in_combat:
            flush_config_to_disk()

        # Renderização Sob Demanda (On-Demand Rendering):
        # Só redesenha o Canvas quando houve eventos relevantes na fila (needs_redraw),
        # ou 1x por segundo se houver um timer de Enrage ativo, ou se um ícone de skill terminou de baixar!
        if not self.is_paused:
            if needs_redraw:
                if self.in_combat and self.combat_start:
                    dur = self._get_fight_duration()
                    self._update_target_label(is_dead=self.target_is_dead, dur=dur)
                    if self.view_mode == "SOLO":
                        self.render_hud(dur)
                    else:
                        self.render_skills(dur)
                else:
                    self._update_target_label(is_dead=self.target_is_dead, dur=0.0)
            else:
                # Atualiza apenas o relógio de Enrage (1x por segundo) caso o Boss tenha Enrage ativo e esteja vivo
                if self.in_combat and not self.target_is_dead and not self.combat_frozen and self.active_target_berserk_epoch is not None:
                    cur_sec = int(now)
                    if cur_sec != self._last_enrage_sec:
                        self._last_enrage_sec = cur_sec
                        self._update_target_label(is_dead=False, dur=self._get_fight_duration())
                # Se estiver na aba SKILLS e um ícone terminou o download em background, carrega na Main Thread
                if self.view_mode == "SKILLS" and self._has_pending_skill_icons and not ICON_MGR.downloading:
                    if self.in_combat and self.combat_start:
                        self.render_skills(self._get_fight_duration())

        self.root.after(120, self.update_loop)

    def _update_target_label(self, is_dead=False, dur=None):
        total_dmg = sum(p["damage"] for p in self.players_combat.values())
        now = time.time()
        if dur is None:
            if self.in_combat and self.combat_start and self.last_hit_t:
                dur = max(0.0, self.last_hit_t - self.combat_start)
            else:
                dur = 0.0

        elapsed_sec = int(max(0.0, (self.last_hit_t - self.combat_start) if (self.in_combat and self.combat_start and self.last_hit_t) else 0.0))
        m, s = divmod(elapsed_sec, 60)
        time_str = f"{m}:{s:02d}"

        party_dps = (total_dmg / max(1.0, dur)) if (self.in_combat and total_dmg > 0) else 0.0
        if party_dps >= 1_000_000:
            pt_dps_str = f"{party_dps/1_000_000:.2f}M/s"
        elif party_dps >= 1_000:
            pt_dps_str = f"{party_dps/1_000:.1f}k/s"
        elif party_dps > 0:
            pt_dps_str = f"{party_dps:,.0f}/s"
        else:
            pt_dps_str = ""

        ttk_sec = None
        if is_dead:
            pct = 0
            ratio = 0.0
        else:
            # Enquanto o alvo está VIVO (!is_dead), garante que max_hp acompanhe cur_hp + total_dmg
            # e que rem_hp seja sempre > 0 para que o TTK (💀 M:SS) NUNCA suma durante a luta do Boss!
            if self.active_target_cur_hp is not None and self.active_target_cur_hp > 0:
                eff_max_hp = max(self.active_target_max_hp or 0, self.active_target_cur_hp + total_dmg)
                self.active_target_max_hp = eff_max_hp
                rem_hp = self.active_target_cur_hp
            elif self.active_target_max_hp and self.active_target_max_hp > total_dmg:
                eff_max_hp = self.active_target_max_hp
                rem_hp = eff_max_hp - total_dmg
            elif self.in_combat and total_dmg > 0:
                eff_max_hp = max(self.active_target_max_hp or 0, 10_000_000, int(total_dmg * 1.35))
                rem_hp = max(1, eff_max_hp - total_dmg)
            else:
                eff_max_hp = self.active_target_max_hp or 0
                rem_hp = eff_max_hp

            if eff_max_hp > 0 and rem_hp > 0:
                pct = max(1, min(100, int((rem_hp / eff_max_hp) * 100)))
                ratio = max(0.02, min(1.0, rem_hp / eff_max_hp))
                # Calcula TTK (Tempo estimado para o Boss morrer no DPS atual do grupo/solo)
                if self.in_combat and dur >= 1.0 and party_dps > 0:
                    ttk_sec = int(math.ceil(rem_hp / party_dps))
            else:
                pct = 100
                ratio = 0.36  # Pílula vermelha sob o nome quando HP máximo não informado

        # Formata informações da direita: %HP · DPS da PT · 💀 Time to Death · Tempo de luta (ou Enrage)
        left_boundary = HUD_WIDTH - 10
        if is_dead:
            # Boss morto: oculta TTD e exibe resumo oficial: "%HP · DPS da PT · Duração final da kill"
            self.monster_canvas.itemconfig(self.m_ttd_txt, text="")
            self.monster_canvas.itemconfig(self.m_info_left, text="")
            self._m_last_ttd = ""
            self._m_last_left = ""
            parts = [f"{pct}%"]
            if pt_dps_str:
                parts.append(pt_dps_str)
            parts.append(time_str)
            dead_text = " · ".join(parts)
            self.monster_canvas.coords(self.m_info_txt, HUD_WIDTH - 10, 13)
            if dead_text != self._m_last_info or self._m_last_color != "#ffffff":
                self.monster_canvas.itemconfig(self.m_info_txt, text=dead_text, fill="#ffffff")
                self._m_last_info = dead_text
                self._m_last_color = "#ffffff"
            bbox_info = self.monster_canvas.bbox(self.m_info_txt)
            left_boundary = bbox_info[0] if bbox_info else (HUD_WIDTH - 90)
        else:
            # Boss vivo
            # 1. Direita: Enrage ou Duração da luta
            if not self.combat_frozen and self.active_target_berserk_epoch is not None:
                enrage_rem = int(math.ceil(self.active_target_berserk_epoch - now))
                if enrage_rem <= 0:
                    right_str = "🔥ENRAGED"
                    r_fill = "#f87171"
                else:
                    em, es = divmod(enrage_rem, 60)
                    if ttk_sec is not None and ttk_sec >= enrage_rem:
                        right_str = f"⚠️🔥{em}:{es:02d}"
                        r_fill = "#fb923c"
                    else:
                        right_str = f"🔥{em}:{es:02d}"
                        r_fill = "#4ade80" if ttk_sec is not None else "#f1f5f9"
            else:
                right_str = time_str
                r_fill = "#cbd5e1"

            self.monster_canvas.coords(self.m_info_txt, HUD_WIDTH - 10, 13)
            if right_str != self._m_last_info or r_fill != self._m_last_color:
                self.monster_canvas.itemconfig(self.m_info_txt, text=right_str, fill=r_fill)
                self._m_last_info = right_str
                self._m_last_color = r_fill
            bbox_r = self.monster_canvas.bbox(self.m_info_txt)
            r_x = bbox_r[0] if bbox_r else (HUD_WIDTH - 10 - max(28, len(right_str) * 7))

            # 2. Time to Death (TTD) em vermelho vivo (#f87171) com ícone de caveira 💀
            if ttk_sec is not None and ttk_sec > 0 and not self.combat_frozen:
                tm, ts = divmod(ttk_sec, 60)
                ttd_str = f"· 💀 {tm}:{ts:02d} ·"
                if ttd_str != self._m_last_ttd:
                    self.monster_canvas.itemconfig(self.m_ttd_txt, text=ttd_str, fill="#f87171")
                    self._m_last_ttd = ttd_str
                self.monster_canvas.coords(self.m_ttd_txt, r_x - 3, 13)
                bbox_ttd = self.monster_canvas.bbox(self.m_ttd_txt)
                ttd_x = bbox_ttd[0] if bbox_ttd else (r_x - 52)
            else:
                if self._m_last_ttd != "":
                    self.monster_canvas.itemconfig(self.m_ttd_txt, text="")
                    self._m_last_ttd = ""
                ttd_x = r_x - 3

            # 3. Esquerda: %HP · DPS da PT
            if self.in_combat or pt_dps_str:
                left_str = f"{pct}% · {pt_dps_str}" if pt_dps_str else f"{pct}% ·"
            else:
                left_str = f"{pct}% ·" if right_str else ""
            if left_str != self._m_last_left:
                self.monster_canvas.itemconfig(self.m_info_left, text=left_str, fill="#ffffff")
                self._m_last_left = left_str
            self.monster_canvas.coords(self.m_info_left, ttd_x - 2, 13)
            bbox_l = self.monster_canvas.bbox(self.m_info_left)
            left_boundary = bbox_l[0] if bbox_l else (ttd_x - max(24, len(left_str) * 7))

        if self.is_hovered:
            self.monster_canvas.itemconfigure(self.m_info_txt, state="hidden")
            self.monster_canvas.itemconfigure(self.m_ttd_txt, state="hidden")
            self.monster_canvas.itemconfigure(self.m_info_left, state="hidden")

        t_name = self.active_target_name if self.active_target_name != "Nenhum alvo" else "Aguardando Alvo"
        if self.view_mode == "SKILLS":
            t_name = f"📊 Skills • {t_name}"
        if self.is_click_through:
            t_name = f"🔒F8 • {t_name}"

        # Evita sobreposição do nome do monstro com as estatísticas à direita
        avail_w = max(40, left_boundary - 20)
        self.monster_canvas.itemconfig(self.m_name_txt, text=t_name)
        bbox_n = self.monster_canvas.bbox(self.m_name_txt)
        if bbox_n and (bbox_n[2] - bbox_n[0]) > avail_w:
            while len(t_name) > 4 and (self.monster_canvas.bbox(self.m_name_txt)[2] - self.monster_canvas.bbox(self.m_name_txt)[0]) > avail_w:
                t_name = t_name[:-2] + "…"
                self.monster_canvas.itemconfig(self.m_name_txt, text=t_name)
        self._m_last_name = t_name

        m_pill = self.pill_renderer.get_monster_pill(ratio if not is_dead else 0.0)
        if m_pill is not self._m_last_pill:
            if hasattr(self, "bg_monster_canvas") and self.bg_monster_canvas:
                self.bg_monster_canvas.itemconfig(self.m_bg_img, image=m_pill)
            self._m_last_pill = m_pill

    def render_hud(self, dur):
        # Lista de participantes válidos da luta atual (preserva 100% do relatório mesmo após saída da dungeon/party!)
        sorted_players = sorted(
            self.players_combat.values(),
            key=lambda x: x["damage"],
            reverse=True
        )

        if not sorted_players:
            self.show_standby_local_player()
            return

        # Ajusta dinamicamente a quantidade de barras visíveis (1 no solo, ou N no grupo!)
        num_bars = min(len(self.rows), len(sorted_players))
        self.set_visible_rows(num_bars)

        top_dmg         = sorted_players[0]["damage"] or 1
        total_party_dmg = sum(p["damage"] for p in sorted_players) or 1

        # Base de cálculo da porcentagem (%) idêntica ao Questlog (combat.cjs share: Ue(n.damage, t.damage)):
        share_basis = total_party_dmg

        for i in range(num_bars):
            row     = self.rows[i]
            p       = sorted_players[i]
            dmg     = p["damage"]
            dps     = dmg / dur
            share   = (dmg / share_basis) * 100.0
            deaths  = p.get("deaths", 0)
            is_dead = bool(p.get("is_dead", False))

            p_class = p.get("class", "templar")
            ratio   = max(0.0, min(1.0, dmg / top_dmg))

            pill   = self.pill_renderer.get_player_pill(p_class, ratio, is_local=p["is_local"], is_dead=is_dead)
            c_icon = self.class_icons.get((p_class, is_dead)) or self.class_icons.get(p_class)

            display_name = p["name"]
            max_n_len = 10 if deaths > 0 else 11
            if len(display_name) > max_n_len:
                display_name = display_name[:max_n_len - 1] + "…"

            cp_val = (
                p.get("combatPower")
                or self.get_player_cp(p["name"], p.get("caster_key"), p.get("is_local", False))
            )
            if cp_val > 0 and p.get("combatPower", 0) == 0:
                p["combatPower"] = cp_val
            cp_str    = f"{cp_val/1000:.1f}K" if cp_val >= 1000 else (f"{cp_val}" if cp_val > 0 else "")
            death_str = str(deaths) if deaths > 0 else ""

            # Formatação de Métricas:
            # 1. Dano Total em Milhões / k (ex: 614.5k, 30.21M, 12.47M)
            if dmg >= 1_000_000:
                dmg_str = f"{dmg/1_000_000:.2f}M"
            elif dmg >= 1_000:
                dmg_str = f"{dmg/1_000:.1f}k"
            else:
                dmg_str = f"{dmg:,.0f}"

            # 2. DPS suave (ex: 7.7k/s, 90.6k/s)
            if dps >= 1000:
                dps_str = f"{dps/1000:.1f}k/s"
            else:
                dps_str = f"{dps:,.0f}/s"

            # 3. Crit % e Crit Hit (Idêntico ao Questlog combat.cjs: hits diretos e crits diretos, sem diluição por DoT)
            p_hits  = p.get("hits", 0)
            p_crits = p.get("crits", 0)
            crit_pct = (p_crits / p_hits * 100.0) if p_hits > 0 else 0.0
            crits_fmt = f"{p_crits/1000:.1f}k" if p_crits >= 1000 else str(p_crits)
            crit_str = f"{crit_pct:.0f}% ({crits_fmt})"

            # 4. Share % (ex: 26.4%)
            share_str = f"{share:.1f}%"

            rank_str = str(i + 1)
            rank_color = "#f59e0b" if p["is_local"] else "#cbd5e1"

            self._update_row(
                row, pill, c_icon,
                rank_str, rank_color,
                display_name, cp_str,
                dmg_str, dps_str, share_str,
                pad_offset=5,
                death_str=death_str,
                crit_str=crit_str,
                p_class=p_class,
                is_dead=is_dead,
                ratio=ratio,
                show_cp_icon=bool(cp_str)
            )

    def render_skills(self, dur):
        local_p = self.players_combat.get("LOCAL")
        if not local_p:
            for p in self.players_combat.values():
                if p["is_local"]:
                    local_p = p
                    break

        if not local_p or not local_p["skills"]:
            self.show_standby_local_player()
            return

        sorted_skills = sorted(local_p["skills"].values(), key=lambda x: x["damage"], reverse=True)
        num_bars      = min(len(self.rows), len(sorted_skills))
        self.set_visible_rows(num_bars)

        max_dmg     = sorted_skills[0]["damage"] or 1
        total_local = local_p["damage"] or 1
        pending_icons = False

        for i in range(num_bars):
            row    = self.rows[i]
            sk     = sorted_skills[i]
            dmg    = sk["damage"]
            sk_dps = dmg / dur
            share  = (dmg / total_local) * 100.0
            sk_hits  = sk.get("hits", 0)
            sk_crits = sk.get("crits", 0)
            crit_pct = (sk_crits / sk_hits * 100.0) if sk_hits > 0 else 0.0
            crits_fmt = f"{sk_crits/1000:.1f}k" if sk_crits >= 1000 else str(sk_crits)
            crit_str = f"{crit_pct:.0f}% ({crits_fmt})"
            total_sk_hits = sk_hits + sk.get("overTimeHits", 0)
            ratio  = max(0.0, min(1.0, dmg / max_dmg))

            pill = self.pill_renderer.get_player_pill("skill", ratio, is_local=False)

            sk_name  = sk["name"]
            sk_icon  = sk.get("icon")
            icon_img = ICON_MGR.get_skill_icon(sk_icon) if sk_icon else None
            if sk_icon and icon_img is None and sk_icon in ICON_MGR.downloading:
                pending_icons = True

            if len(sk_name) > 13:
                sk_name = sk_name[:12] + "…"

            if sk_dps >= 1000:
                dps_num = f"{sk_dps/1000:.1f}k/s"
            else:
                dps_num = f"{sk_dps:,.0f}/s"

            if dmg >= 1_000_000:
                dmg_num = f"{dmg/1_000_000:.2f}M"
            elif dmg >= 1_000:
                dmg_num = f"{dmg/1_000:.1f}k"
            else:
                dmg_num = f"{dmg:,.0f}"

            rank_str = str(i + 1)
            rank_color = "#38bdf8"

            self._update_row(
                row, pill, icon_img,
                rank_str, rank_color,
                sk_name, f"⚡{total_sk_hits}",
                dmg_num, dps_num, f"{share:.1f}%",
                pad_offset=5,
                death_str="",
                crit_str=crit_str,
                p_class="skill",
                is_dead=False,
                ratio=ratio,
                show_cp_icon=False
            )

        self._has_pending_skill_icons = pending_icons

    def on_close(self):
        flush_config_to_disk(force=True)
        self.sniffer.stop()
        if hasattr(self, "bg_win") and self.bg_win:
            try:
                self.bg_win.destroy()
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass
        try:
            self.taskbar_win.destroy()
        except Exception:
            pass
        sys.exit(0)

def main():
    check_or_request_admin()
    root = tk.Tk()
    OverlayDPSMeter(root)
    root.mainloop()

if __name__ == "__main__":
    main()
