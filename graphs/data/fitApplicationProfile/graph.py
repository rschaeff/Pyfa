from logbook import Logger

from eos.saveddata.fit import Fit
from graphs.data.base import FitGraph, XDef, YDef, Input, VectorDef
from graphs.data.fitApplicationProfile.getter import (
    Distance2OptimalAmmoDpsGetter,
    Distance2OptimalAmmoVolleyGetter,
)
from graphs.data.fitDamageStats.cache import ProjectedDataCache
from service.const import GraphCacheCleanupReason
from service.settings import GraphSettings

pyfalog = Logger(__name__)


class FitAmmoOptimalDpsGraph(FitGraph):

    # Graph definition
    internalName = 'ammoOptimalDpsGraph'
    name = 'Application Profile'
    xDefs = [
        XDef(handle='distance', unit='km', label='Distance', mainInput=('distance', 'km'))]
    inputs = [
        Input(handle='distance', unit='km', label='Distance', iconID=None, defaultValue=None, defaultRange=(0, 150), mainTooltip='Distance to target')]

    # Vector controls for attacker and target velocity/angle (same as DPS graph)
    srcVectorDef = VectorDef(lengthHandle='atkSpeed', lengthUnit='%', angleHandle='atkAngle', angleUnit='degrees', label='Attacker')
    tgtVectorDef = VectorDef(lengthHandle='tgtSpeed', lengthUnit='%', angleHandle='tgtAngle', angleUnit='degrees', label='Target')

    sources = {Fit}
    _limitToOutgoingProjected = True
    hasTargets = True
    srcExtraCols = ('Dps', 'Volley', 'Speed', 'SigRadius', 'Radius')

    @property
    def tgtExtraCols(self):
        cols = ['Target Resists', 'Speed', 'SigRadius', 'Radius']
        return cols

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

    _getters = {
        ('distance', 'dps'): Distance2OptimalAmmoDpsGetter,
        ('distance', 'volley'): Distance2OptimalAmmoVolleyGetter}

    def __init__(self):
        super().__init__()
        self._projectedCache = ProjectedDataCache()

    def _clearInternalCache(self, reason, extraData):
        if reason in (GraphCacheCleanupReason.fitChanged, GraphCacheCleanupReason.fitRemoved):
            self._projectedCache.clearForFit(extraData)
            # Clear weapon and projected caches for this fit
            for cache_name in ('_ammo_weapon_cache', '_ammo_projected_cache'):
                cache = getattr(self, cache_name, None)
                if cache:
                    keys_to_remove = [k for k in cache if k[0] == extraData]
                    for key in keys_to_remove:
                        del cache[key]
            # Clear charge cache on fit change
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
