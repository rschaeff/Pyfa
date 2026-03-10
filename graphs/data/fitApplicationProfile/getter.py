from eos.const import FittingHardpoint
from logbook import Logger

from graphs.data.base.getter import SmoothPointGetter
from graphs.data.fitDamageStats.calc.projected import (
    getScramRange, getScrammables
)
from service.settings import GraphSettings
from .calc.valid_charges import getValidChargesForModule

from .calc.turret import (
    getTurretBaseStats,
    getSkillMultiplier
)
from .calc.charges import (
    filterChargesByQuality,
    precomputeChargeData,
    getLongestRangeMultiplier
)
from .calc.optimize_ammo import (
    volleyToDps,
    calculateTransitions,
    getVolleyAtDistance
)
from .calc.projected import (
    buildProjectedCache
)
from .calc.launcher import (
    getAllMultipliers as getLauncherMultipliers,
    precomputeMissileChargeData,
    getMaxEffectiveRange as getMissileMaxEffectiveRange,
    calculateTransitions as calculateMissileTransitions,
    getVolleyAtDistance as getMissileVolleyAtDistance,
    volleyToDps as missileVolleyToDps
)


pyfalog = Logger(__name__)


# =============================================================================
# Max Effective Range Calculation
# =============================================================================

def getMaxEffectiveRange(turretBase, charges):
    longestRangeMult = getLongestRangeMultiplier(charges)
    effectiveOptimal = turretBase['optimal'] * longestRangeMult
    effectiveMaxRange = effectiveOptimal + turretBase['falloff'] * 3.1
    return int(effectiveMaxRange)


def getTurretRangeInfo(mod, qualityTier, chargeCache=None):
    turretBase = getTurretBaseStats(mod)
    cycleParams = mod.getCycleParameters()
    if cycleParams is None:
        return None
    cycleTimeMs = cycleParams.averageTime

    chargeCacheKey = (mod.item.ID, qualityTier)
    if chargeCache is not None and chargeCacheKey in chargeCache:
        charges = chargeCache[chargeCacheKey]
    else:
        allCharges = list(getValidChargesForModule(mod))
        charges = filterChargesByQuality(allCharges, qualityTier)
        if chargeCache is not None:
            chargeCache[chargeCacheKey] = charges

    if not charges:
        return None

    maxEffectiveRange = getMaxEffectiveRange(turretBase, charges)

    return {
        'turret_base': turretBase,
        'charges': charges,
        'max_effective_range': maxEffectiveRange,
        'cycle_time_ms': cycleTimeMs
    }


# =============================================================================
# Launcher Max Range Functions
# =============================================================================

def getLauncherRangeInfo(mod, qualityTier, shipRadius, chargeCache=None):
    cycleParams = mod.getCycleParameters()
    if cycleParams is None:
        return None
    cycleTimeMs = cycleParams.averageTime

    chargeCacheKey = (mod.item.ID, qualityTier)
    if chargeCache is not None and chargeCacheKey in chargeCache:
        charges = chargeCache[chargeCacheKey]
    else:
        allCharges = list(getValidChargesForModule(mod))
        charges = filterChargesByQuality(allCharges, qualityTier)
        if chargeCache is not None:
            chargeCache[chargeCacheKey] = charges

    if not charges:
        return None

    damageMults, flightMults, appMults = getLauncherMultipliers(mod)
    launcherDamageMult = mod.getModifiedItemAttr('damageMultiplier') or 1

    chargeData = precomputeMissileChargeData(
        mod, charges, cycleTimeMs, shipRadius,
        damageMults, flightMults, appMults,
        tgtResists=None
    )

    if not chargeData:
        return None

    maxEffectiveRange = getMissileMaxEffectiveRange(chargeData)

    return {
        'charges': charges,
        'charge_data': chargeData,
        'max_effective_range': maxEffectiveRange,
        'cycle_time_ms': cycleTimeMs,
        'damage_mults': damageMults,
        'flight_mults': flightMults,
        'app_mults': appMults,
        'launcher_damage_mult': launcherDamageMult
    }


# =============================================================================
# Dominant Group Detection
# =============================================================================

def countWeaponGroups(src):
    turretCount = 0
    launcherCount = 0
    for mod in src.item.activeModulesIter():
        if mod.getModifiedItemAttr('miningAmount'):
            continue
        if mod.hardpoint == FittingHardpoint.TURRET:
            turretCount += 1
        elif mod.hardpoint == FittingHardpoint.MISSILE:
            launcherCount += 1
    return turretCount, launcherCount


def getDominantWeaponType(src):
    turretCount, launcherCount = countWeaponGroups(src)
    if turretCount == 0 and launcherCount == 0:
        return None
    if turretCount >= launcherCount:
        return 'turret'
    else:
        return 'launcher'


# =============================================================================
# Cache Building
# =============================================================================

def buildTurretCacheEntry(mod, qualityTier, tgtResists, baseTrackingParams,
                          projectedCache, chargeCache=None, rangeInfo=None):
    if rangeInfo is not None:
        turretBase = rangeInfo['turret_base']
        charges = rangeInfo['charges']
        cycleTimeMs = rangeInfo['cycle_time_ms']
    else:
        turretBase = getTurretBaseStats(mod)
        cycleParams = mod.getCycleParameters()
        if cycleParams is None:
            return None
        cycleTimeMs = cycleParams.averageTime
        chargeCacheKey = (mod.item.ID, qualityTier)
        if chargeCache is not None and chargeCacheKey in chargeCache:
            charges = chargeCache[chargeCacheKey]
        else:
            allCharges = list(getValidChargesForModule(mod))
            charges = filterChargesByQuality(allCharges, qualityTier)
            if chargeCache is not None:
                chargeCache[chargeCacheKey] = charges
        if not charges:
            return None

    if not charges:
        return None

    skillMult = getSkillMultiplier(mod)
    chargeData = precomputeChargeData(turretBase, charges, skillMult, tgtResists)

    maxEffectiveOptimal = max(cd['effective_optimal'] for cd in chargeData)
    maxEffectiveFalloff = max(cd['effective_falloff'] for cd in chargeData)
    maxEffectiveRange = int(maxEffectiveOptimal + maxEffectiveFalloff * 3.1)

    transitions = calculateTransitions(
        chargeData, turretBase, baseTrackingParams,
        projectedCache,
        maxDistance=maxEffectiveRange
    )

    return {
        'charge_data': chargeData,
        'transitions': transitions,
        'turret_base': turretBase,
        'cycle_time_ms': cycleTimeMs,
        'count': 1
    }


def buildLauncherCacheEntry(mod, qualityTier, tgtResists, shipRadius,
                            baseTgtSpeed, baseTgtSigRadius,
                            projectedCache, chargeCache=None, rangeInfo=None):
    if rangeInfo is not None:
        charges = rangeInfo['charges']
        cycleTimeMs = rangeInfo['cycle_time_ms']
        damageMults = rangeInfo['damage_mults']
        flightMults = rangeInfo['flight_mults']
        appMults = rangeInfo['app_mults']
    else:
        cycleParams = mod.getCycleParameters()
        if cycleParams is None:
            return None
        cycleTimeMs = cycleParams.averageTime
        chargeCacheKey = (mod.item.ID, qualityTier)
        if chargeCache is not None and chargeCacheKey in chargeCache:
            charges = chargeCache[chargeCacheKey]
        else:
            allCharges = list(getValidChargesForModule(mod))
            charges = filterChargesByQuality(allCharges, qualityTier)
            if chargeCache is not None:
                chargeCache[chargeCacheKey] = charges
        if not charges:
            return None
        damageMults, flightMults, appMults = getLauncherMultipliers(mod)

    chargeData = precomputeMissileChargeData(
        mod, charges, cycleTimeMs, shipRadius,
        damageMults, flightMults, appMults, tgtResists
    )

    if not chargeData:
        return None

    maxEffectiveRange = getMissileMaxEffectiveRange(chargeData)

    transitions = calculateMissileTransitions(
        chargeData, baseTgtSpeed, baseTgtSigRadius,
        projectedCache,
        maxDistance=int(maxEffectiveRange)
    )

    return {
        'charge_data': chargeData,
        'transitions': transitions,
        'cycle_time_ms': cycleTimeMs,
        'count': 1
    }


# =============================================================================
# Y-Axis Mixins
# =============================================================================

class YOptimalAmmoDpsMixin:

    def _getOptimalDpsAtDistance(self, distance, weaponCache, trackingParams, projectedCache, weaponType):
        totalDps = 0
        if weaponType == 'turret':
            for groupInfo in weaponCache.values():
                volley, _ = getVolleyAtDistance(
                    groupInfo['transitions'],
                    groupInfo['charge_data'],
                    groupInfo['turret_base'],
                    distance,
                    trackingParams,
                    projectedCache
                )
                dps = volleyToDps(volley, groupInfo['cycle_time_ms'])
                totalDps += dps * groupInfo['count']
        else:
            for groupInfo in weaponCache.values():
                volley, _ = getMissileVolleyAtDistance(
                    groupInfo['transitions'],
                    groupInfo['charge_data'],
                    distance,
                    trackingParams['tgtSpeed'],
                    trackingParams['tgtSigRadius'],
                    projectedCache
                )
                dps = missileVolleyToDps(volley, groupInfo['cycle_time_ms'])
                totalDps += dps * groupInfo['count']
        return totalDps


class YOptimalAmmoVolleyMixin:

    def _getOptimalVolleyAtDistance(self, distance, weaponCache, trackingParams, projectedCache, weaponType):
        totalVolley = 0
        if weaponType == 'turret':
            for groupInfo in weaponCache.values():
                volley, _ = getVolleyAtDistance(
                    groupInfo['transitions'],
                    groupInfo['charge_data'],
                    groupInfo['turret_base'],
                    distance,
                    trackingParams,
                    projectedCache
                )
                totalVolley += volley * groupInfo['count']
        else:
            for groupInfo in weaponCache.values():
                volley, _ = getMissileVolleyAtDistance(
                    groupInfo['transitions'],
                    groupInfo['charge_data'],
                    distance,
                    trackingParams['tgtSpeed'],
                    trackingParams['tgtSigRadius'],
                    projectedCache
                )
                totalVolley += volley * groupInfo['count']
        return totalVolley


# =============================================================================
# X-Axis Mixin
# =============================================================================

class XDistanceMixin(SmoothPointGetter):

    _baseResolution = 100

    def _getCommonData(self, miscParams, src, tgt):
        qualityTier = miscParams.get('ammoQuality', 'all')
        ignoreResists = GraphSettings.getInstance().get('ammoOptimalIgnoreResists')
        applyProjected = GraphSettings.getInstance().get('ammoOptimalApplyProjected')

        tgtResists = None if (ignoreResists or tgt is None) else tgt.getResists()
        tgtSpeed = miscParams.get('tgtSpeed', 0) or 0
        tgtSigRadius = tgt.getSigRadius() if tgt else 0
        shipRadius = src.getRadius()

        weaponType = getDominantWeaponType(src)

        fit_id = src.item.ID

        atkSpeed = miscParams.get('atkSpeed', 0) or 0
        atkAngle = miscParams.get('atkAngle', 0) or 0
        tgtAngle = miscParams.get('tgtAngle', 0) or 0

        weaponCacheKey = (fit_id, weaponType, qualityTier, tgtResists, applyProjected, tgtSpeed, tgtSigRadius, atkSpeed, atkAngle, tgtAngle)
        projectedCacheKey = (fit_id, tgtSpeed, tgtSigRadius, atkSpeed, atkAngle, tgtAngle)

        # Initialize graph caches if needed
        if not hasattr(self.graph, '_ammo_weapon_cache'):
            self.graph._ammo_weapon_cache = {}
        if not hasattr(self.graph, '_ammo_charge_cache'):
            self.graph._ammo_charge_cache = {}
        if not hasattr(self.graph, '_ammo_projected_cache'):
            self.graph._ammo_projected_cache = {}

        commonData = {
            'applyProjected': applyProjected,
            'src_radius': shipRadius,
            'weapon_type': weaponType,
        }

        # Add projected effect data if enabled
        if applyProjected:
            commonData['srcScramRange'] = getScramRange(src=src)
            commonData['tgtScrammables'] = getScrammables(tgt=tgt) if tgt else ()
            webMods, tpMods = self.graph._projectedCache.getProjModData(src)
            webDrones, tpDrones = self.graph._projectedCache.getProjDroneData(src)
            webFighters, tpFighters = self.graph._projectedCache.getProjFighterData(src)
            commonData['webMods'] = webMods
            commonData['tpMods'] = tpMods
            commonData['webDrones'] = webDrones
            commonData['tpDrones'] = tpDrones
            commonData['webFighters'] = webFighters
            commonData['tpFighters'] = tpFighters

        if weaponCacheKey in self.graph._ammo_weapon_cache:
            cached_weapon = self.graph._ammo_weapon_cache[weaponCacheKey]
            commonData['weapon_cache'] = cached_weapon
            commonData['projected_cache'] = self.graph._ammo_projected_cache.get(projectedCacheKey, {})
            return commonData

        if weaponType is None:
            commonData['weapon_cache'] = {}
            commonData['projected_cache'] = {}
            return commonData

        # PHASE 1: Determine max effective range per weapon type
        weaponRangeInfos = {}
        maxEffectiveRange = 0

        if weaponType == 'turret':
            hardpointType = FittingHardpoint.TURRET
        else:
            hardpointType = FittingHardpoint.MISSILE

        for mod in src.item.activeModulesIter():
            if mod.hardpoint != hardpointType:
                continue
            if mod.getModifiedItemAttr('miningAmount'):
                continue

            key = mod.item.ID
            if key not in weaponRangeInfos:
                if weaponType == 'turret':
                    rangeInfo = getTurretRangeInfo(mod, qualityTier, self.graph._ammo_charge_cache)
                else:
                    if mod.charge is None:
                        # For empty launchers, temporarily load a charge to extract multipliers
                        chargeCacheKey = (mod.item.ID, qualityTier)
                        validCharges = self.graph._ammo_charge_cache.get(chargeCacheKey)
                        if validCharges is None:
                            allCharges = list(getValidChargesForModule(mod))
                            validCharges = filterChargesByQuality(allCharges, qualityTier)
                            self.graph._ammo_charge_cache[chargeCacheKey] = validCharges

                        if validCharges:
                            tempCharge = validCharges[0]
                            try:
                                mod.charge = tempCharge
                                if mod.owner:
                                    mod.owner.calculated = False
                                    mod.owner.calculateModifiedAttributes()
                                rangeInfo = getLauncherRangeInfo(mod, qualityTier, shipRadius, self.graph._ammo_charge_cache)
                            except (KeyboardInterrupt, SystemExit):
                                raise
                            except Exception as e:
                                pyfalog.error(f"Error simulating charge for {mod.item.name}: {e}")
                                rangeInfo = None
                            finally:
                                mod.charge = None
                                if mod.owner:
                                    mod.owner.calculated = False
                                    mod.owner.calculateModifiedAttributes()
                        else:
                            rangeInfo = None
                    else:
                        rangeInfo = getLauncherRangeInfo(mod, qualityTier, shipRadius, self.graph._ammo_charge_cache)

                if rangeInfo:
                    weaponRangeInfos[key] = rangeInfo
                    if rangeInfo['max_effective_range'] > maxEffectiveRange:
                        maxEffectiveRange = rangeInfo['max_effective_range']

        if not weaponRangeInfos:
            commonData['weapon_cache'] = {}
            commonData['projected_cache'] = {}
            return commonData

        # PHASE 2: Build/extend projected cache
        existingCache = self.graph._ammo_projected_cache.get(projectedCacheKey)

        baseTrackingParams = {
            'atkSpeed': atkSpeed,
            'atkAngle': atkAngle,
            'atkRadius': shipRadius,
            'tgtSpeed': tgtSpeed,
            'tgtAngle': tgtAngle,
            'tgtRadius': tgt.getRadius() if tgt else 0,
            'tgtSigRadius': tgtSigRadius
        }

        projectedCache = buildProjectedCache(
            src=src, tgt=tgt, commonData=commonData,
            baseTgtSpeed=tgtSpeed, baseTgtSigRadius=tgtSigRadius,
            maxDistance=maxEffectiveRange, resolution=100,
            existingCache=existingCache
        )

        self.graph._ammo_projected_cache[projectedCacheKey] = projectedCache
        commonData['projected_cache'] = projectedCache

        # PHASE 3: Build weapon cache with transitions
        weaponCache = {}
        for mod in src.item.activeModulesIter():
            if mod.hardpoint != hardpointType:
                continue
            if mod.getModifiedItemAttr('miningAmount'):
                continue

            key = mod.item.ID
            if key not in weaponCache:
                rangeInfo = weaponRangeInfos.get(key)
                if rangeInfo:
                    if weaponType == 'turret':
                        entry = buildTurretCacheEntry(
                            mod, qualityTier, tgtResists, baseTrackingParams,
                            projectedCache, self.graph._ammo_charge_cache,
                            rangeInfo=rangeInfo
                        )
                    else:
                        entry = buildLauncherCacheEntry(
                            mod, qualityTier, tgtResists, shipRadius,
                            tgtSpeed, tgtSigRadius,
                            projectedCache, self.graph._ammo_charge_cache,
                            rangeInfo=rangeInfo
                        )
                    if entry:
                        weaponCache[key] = entry
            else:
                weaponCache[key]['count'] += 1

        self.graph._ammo_weapon_cache[weaponCacheKey] = weaponCache
        commonData['weapon_cache'] = weaponCache

        return commonData

    def _buildTrackingParams(self, distance, miscParams, src, tgt, commonData):
        tgtSpeed = miscParams.get('tgtSpeed', 0) or 0
        tgtSigRadius = tgt.getSigRadius() if tgt else 0

        if tgtSigRadius == 0:
            return None

        return {
            'atkSpeed': miscParams.get('atkSpeed', 0) or 0,
            'atkAngle': miscParams.get('atkAngle', 0) or 0,
            'atkRadius': commonData.get('src_radius', 0),
            'tgtSpeed': tgtSpeed,
            'tgtAngle': miscParams.get('tgtAngle', 0) or 0,
            'tgtRadius': tgt.getRadius() if tgt else 0,
            'tgtSigRadius': tgtSigRadius
        }

    def _calculatePoint(self, x, miscParams, src, tgt, commonData):
        weaponCache = commonData.get('weapon_cache', {})
        weaponType = commonData.get('weapon_type')
        if not weaponCache:
            return 0

        trackingParams = self._buildTrackingParams(x, miscParams, src, tgt, commonData)
        projectedCache = commonData.get('projected_cache', {})

        if hasattr(self, '_getOptimalDpsAtDistance'):
            return self._getOptimalDpsAtDistance(x, weaponCache, trackingParams, projectedCache, weaponType)
        elif hasattr(self, '_getOptimalVolleyAtDistance'):
            return self._getOptimalVolleyAtDistance(x, weaponCache, trackingParams, projectedCache, weaponType)
        return 0


# =============================================================================
# Getter Classes
# =============================================================================

class Distance2OptimalAmmoDpsGetter(XDistanceMixin, YOptimalAmmoDpsMixin):
    pass


class Distance2OptimalAmmoVolleyGetter(XDistanceMixin, YOptimalAmmoVolleyMixin):
    pass
