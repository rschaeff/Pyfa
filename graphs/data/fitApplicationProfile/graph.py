import colorsys
import re
from bisect import bisect_right

from logbook import Logger

from eos.saveddata.fit import Fit
from graphs.data.base import FitGraph, XDef, YDef, Input, InputChoice, VectorDef
from graphs.data.fitApplicationProfile.getter import (
    Distance2OptimalAmmoDpsGetter,
    Distance2OptimalAmmoVolleyGetter,
)
from graphs.data.fitDamageStats.cache import ProjectedDataCache
from service.const import GraphCacheCleanupReason
from service.settings import GraphSettings

pyfalog = Logger(__name__)


# =============================================================================
# Ammo Color Palette
# =============================================================================

# Turret ammo colors (RGB 0-255)
_TURRET_COLORS = {
    # Hybrid - Short Range
    'Null': (179, 179, 166),
    'Void': (128, 26, 51),
    # Hybrid - Long Range
    'Spike': (194, 255, 43),
    'Javelin': (112, 251, 0),
    # Hybrid - Standard
    'Antimatter': (15, 0, 0),
    'Iridium': (26, 179, 179),
    'Lead': (114, 120, 125),
    'Plutonium': (0, 150, 68),
    'Thorium': (148, 127, 115),
    'Uranium': (94, 230, 73),
    'Tungsten': (8, 0, 38),
    'Iron': (153, 77, 77),
    # Energy - Short Range
    'Scorch': (235, 79, 255),
    'Conflagration': (0, 184, 64),
    # Energy - Long Range
    'Gleam': (181, 145, 94),
    'Aurora': (166, 18, 55),
    # Energy - Standard
    'Multifrequency': (204, 204, 204),
    'Gamma': (5, 102, 242),
    'Xray': (0, 189, 134),
    'Ultraviolet': (107, 0, 189),
    'Standard': (230, 179, 0),
    'Infrared': (242, 64, 5),
    'Microwave': (242, 142, 5),
    'Radio': (227, 10, 10),
    # Projectile - Short Range
    'Quake': (199, 154, 82),
    'Hail': (255, 153, 0),
    # Projectile - Long Range
    'Tremor': (74, 64, 47),
    'Barrage': (196, 83, 2),
    # Projectile - Standard
    'Carbonized Lead': (192, 81, 214),
    'Depleted Uranium': (103, 0, 207),
    'EMP': (25, 194, 194),
    'Fusion': (222, 140, 33),
    'Nuclear': (122, 184, 15),
    'Phased Plasma': (184, 15, 54),
    'Proton': (55, 116, 117),
    'Titanium Sabot': (54, 75, 94),
    # Exotic Plasma
    'Occult': (189, 0, 38),
    'Mystic': (252, 174, 145),
    'Tetryon': (240, 59, 32),
    'Baryon': (253, 141, 60),
    'Meson': (254, 204, 92),
    # Vorton
    'ElectroPunch Ultra': (37, 52, 148),
    'StrikeSnipe Ultra': (103, 169, 207),
    'BlastShot Condenser Pack': (49, 163, 84),
    'GalvaSurge Condenser Pack': (44, 127, 184),
    'MesmerFlux Condenser Pack': (65, 182, 196),
    'SlamBolt Condenser Pack': (194, 230, 153),
}

# Missile colors are generated from damage-type hue + charge-type saturation/value
_MISSILE_HUES = {'Mjolnir': 210, 'Inferno': 0, 'Scourge': 180, 'Nova': 30}
_MISSILE_SV = {
    'Rage': (90, 55), 'Fury': (90, 55), 'Faction': (55, 90),
    'Precision': (50, 85), 'Javelin': (50, 45), 'T1': (25, 90),
}


def _build_ammo_colors():
    """Build complete ammo color lookup (base name -> RGB 0-1 for matplotlib)."""
    colors = {}
    for name, rgb in _TURRET_COLORS.items():
        colors[name] = (rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)
    for dmg, hue in _MISSILE_HUES.items():
        for variant, (s, v) in _MISSILE_SV.items():
            r, g, b = colorsys.hsv_to_rgb(hue / 360, s / 100, v / 100)
            if variant == 'Faction':
                colors['Faction {}'.format(dmg)] = (r, g, b)
            elif variant == 'T1':
                colors[dmg] = (r, g, b)
            else:
                colors['{} {}'.format(dmg, variant)] = (r, g, b)
    return colors


AMMO_COLORS = _build_ammo_colors()

# Patterns for stripping EVE item names down to base ammo name
_MISSILE_SUFFIXES = [
    ' XL Torpedo', ' XL Cruise Missile',
    ' Light Missile', ' Heavy Missile', ' Heavy Assault Missile',
    ' Cruise Missile', ' Torpedo', ' Auto-Targeting Missile',
]
_FACTION_PREFIXES = [
    'Republic Fleet ', 'Imperial Navy ', 'Caldari Navy ', 'Federation Navy ',
    'Dread Guristas ', 'True Sansha ', 'Shadow Serpentis ', 'Domination ',
    'Dark Blood ', 'Arch Angel ', 'Guristas ', 'Sansha ', 'Serpentis ',
    'Blood ', 'Angel ',
]
_SIZE_RE = re.compile(r'\s+(S|M|L|XL)$', re.IGNORECASE)
_CHARGE_RE = re.compile(r'\s+Charge$', re.IGNORECASE)


def _get_base_name(ammo_name):
    """Strip size suffixes, missile type suffixes, and faction prefixes to get base ammo name."""
    if not ammo_name:
        return None
    name = ammo_name
    is_missile = False
    for suffix in _MISSILE_SUFFIXES:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            is_missile = True
            break
    if not is_missile:
        for prefix in _FACTION_PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
    name = _SIZE_RE.sub('', name)
    name = _CHARGE_RE.sub('', name)
    return name


def _get_ammo_color(ammo_name):
    """Look up matplotlib-ready RGB color for an ammo name. Returns None if unknown."""
    base = _get_base_name(ammo_name)
    if base is None:
        return None
    if base in AMMO_COLORS:
        return AMMO_COLORS[base]
    # For missiles, try stripping faction prefix for the color lookup
    for prefix in _FACTION_PREFIXES:
        if base.startswith(prefix):
            stripped = base[len(prefix):]
            if stripped in AMMO_COLORS:
                return AMMO_COLORS[stripped]
            # Faction missiles map to the "Faction <DmgType>" color
            for dmg in _MISSILE_HUES:
                if stripped.startswith(dmg):
                    key = 'Faction {}'.format(dmg)
                    if key in AMMO_COLORS:
                        return AMMO_COLORS[key]
    return None


# =============================================================================
# Graph Class
# =============================================================================

class FitAmmoOptimalDpsGraph(FitGraph):

    internalName = 'ammoOptimalDpsGraph'
    name = 'Application Profile'
    xDefs = [
        XDef(handle='distance', unit='km', label='Distance', mainInput=('distance', 'km'))]
    inputs = [
        Input(handle='distance', unit='km', label='Distance', iconID=None, defaultValue=None, defaultRange=(0, 150), mainTooltip='Distance to target')]

    srcVectorDef = VectorDef(lengthHandle='atkSpeed', lengthUnit='%', angleHandle='atkAngle', angleUnit='degrees', label='Attacker')
    tgtVectorDef = VectorDef(lengthHandle='tgtSpeed', lengthUnit='%', angleHandle='tgtAngle', angleUnit='degrees', label='Target')

    sources = {Fit}
    hasTargets = True
    srcExtraCols = ('Dps', 'Volley', 'Speed', 'SigRadius', 'Radius')

    @property
    def tgtExtraCols(self):
        return ['Target Resists', 'Speed', 'SigRadius', 'Radius']

    @property
    def yDefs(self):
        ignoreResists = GraphSettings.getInstance().get('ammoOptimalIgnoreResists')
        return [
            YDef(handle='dps', unit=None, label='DPS' if ignoreResists else 'Effective DPS'),
            YDef(handle='volley', unit=None, label='Volley' if ignoreResists else 'Effective Volley')]

    _normalizers = {
        ('distance', 'km'): lambda v, src, tgt: None if v is None else v * 1000,
        ('atkSpeed', '%'): lambda v, src, tgt: v / 100 * src.getMaxVelocity(),
        ('tgtSpeed', '%'): lambda v, src, tgt: v / 100 * tgt.getMaxVelocity()}

    _denormalizers = {
        ('distance', 'km'): lambda v, src, tgt: None if v is None else v / 1000,
        ('tgtSpeed', '%'): lambda v, src, tgt: v * 100 / tgt.getMaxVelocity()}

    _limiters = {}

    choices = (
        InputChoice(
            handle='ammoQuality',
            label='Ammo quality:',
            options=(('all', 'All'), ('navy', 'Navy+'), ('t1', 'T1 only')),
            defaultValue='all'),
    )

    _getters = {
        ('distance', 'dps'): Distance2OptimalAmmoDpsGetter,
        ('distance', 'volley'): Distance2OptimalAmmoVolleyGetter}

    def __init__(self):
        super().__init__()
        self._projectedCache = ProjectedDataCache()

    # -------------------------------------------------------------------------
    # Segmented rendering
    # -------------------------------------------------------------------------

    def renderLine(self, axes, xs, ys, color, lineStyle, src, tgt):
        if len(xs) <= 1:
            axes.plot(xs, ys, color=color, linestyle=lineStyle, marker='.')
            return

        segments = self._getSegments(xs, src, tgt)
        if not segments:
            axes.plot(xs, ys, color=color, linestyle=lineStyle)
            return

        # Draw each segment with its ammo color, overlapping by one point
        # so segments connect visually
        for startIdx, endIdx, ammoName in segments:
            segColor = _get_ammo_color(ammoName) or color
            segXs = xs[startIdx:endIdx + 1]
            segYs = ys[startIdx:endIdx + 1]
            if len(segXs) >= 2:
                axes.plot(segXs, segYs, color=segColor, linestyle=lineStyle)
            elif len(segXs) == 1:
                axes.plot(segXs, segYs, color=segColor, linestyle=lineStyle, marker='.')

    def _getSegments(self, xs, src, tgt):
        """Map denormalized X values (km) to ammo name segments using cached transitions.

        Returns list of (startIdx, endIdx, ammoName) or None if no data.
        """
        weaponCache = self._findWeaponCache(src, tgt)
        if not weaponCache:
            return None

        # Merge transitions from all weapon groups.  For mixed-group fits the
        # "dominant" group (most modules) drives the coloring — a simplification
        # that avoids blending colors from independent turret types.
        bestGroup = max(weaponCache.values(), key=lambda g: g['count'])
        transitions = bestGroup.get('transitions')
        if not transitions:
            return None

        # transitions: [(dist_m, chargeIdx, chargeName, volley), ...]
        # Sorted ascending by distance.  Build a lookup: sorted boundary
        # distances and the ammo name that starts at each boundary.
        boundaries = [t[0] for t in transitions]
        names = [t[2] for t in transitions]

        segments = []
        currentStart = 0
        currentAmmo = self._ammoAt(xs[0] * 1000, boundaries, names)

        for i in range(1, len(xs)):
            ammo = self._ammoAt(xs[i] * 1000, boundaries, names)
            if ammo != currentAmmo:
                segments.append((currentStart, i, currentAmmo))
                currentStart = i
                currentAmmo = ammo
        segments.append((currentStart, len(xs) - 1, currentAmmo))
        return segments

    def _findWeaponCache(self, src, tgt):
        """Find the weapon cache entry matching this src x tgt pair."""
        cache = getattr(self, '_ammo_weapon_cache', None)
        if not cache:
            return None
        fitId = src.item.ID
        # Weapon cache keys start with fit_id; find the first match
        for key, val in cache.items():
            if key[0] == fitId:
                return val
        return None

    @staticmethod
    def _ammoAt(distance_m, boundaries, names):
        """Return the ammo name active at a given distance using sorted boundaries."""
        idx = bisect_right(boundaries, distance_m) - 1
        if idx < 0:
            idx = 0
        return names[idx]

    # -------------------------------------------------------------------------
    # Cache management
    # -------------------------------------------------------------------------

    def _clearInternalCache(self, reason, extraData):
        if reason in (GraphCacheCleanupReason.fitChanged, GraphCacheCleanupReason.fitRemoved):
            self._projectedCache.clearForFit(extraData)
            for cache_name in ('_ammo_weapon_cache', '_ammo_projected_cache'):
                cache = getattr(self, cache_name, None)
                if cache:
                    keys_to_remove = [k for k in cache if k[0] == extraData]
                    for key in keys_to_remove:
                        del cache[key]
            if hasattr(self, '_ammo_charge_cache'):
                self._ammo_charge_cache = {}

        elif reason in (GraphCacheCleanupReason.profileChanged, GraphCacheCleanupReason.profileRemoved):
            for cache_name in ('_ammo_weapon_cache', '_ammo_projected_cache'):
                if hasattr(self, cache_name):
                    setattr(self, cache_name, {})

        elif reason == GraphCacheCleanupReason.graphSwitched:
            self._projectedCache.clearAll()
            for cache_name in ('_ammo_weapon_cache', '_ammo_projected_cache', '_ammo_charge_cache'):
                if hasattr(self, cache_name):
                    setattr(self, cache_name, {})

        elif reason in (GraphCacheCleanupReason.inputChanged, GraphCacheCleanupReason.optionChanged):
            for cache_name in ('_ammo_weapon_cache', '_ammo_projected_cache'):
                if hasattr(self, cache_name):
                    setattr(self, cache_name, {})
