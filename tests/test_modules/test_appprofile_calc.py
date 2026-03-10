"""
Pure math tests for Application Profile calc modules.

These test the EVE Online weapon mechanics formulas without requiring
any eos objects, database access, or wxPython.

We use importlib to load the calc modules directly, bypassing the
graphs package __init__.py which imports wxPython GUI code.
"""

"""
Pure math tests for Application Profile calc modules.

These test the EVE Online weapon mechanics formulas without requiring
database access. Requires wxPython installed (pyfa's graphs package
init imports GUI code). Run on a machine with full pyfa dependencies.
"""

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest

from graphs.data.fitApplicationProfile.calc.turret import (
    calcAngularSpeed,
    calcTrackingFactor,
    calcTurretDamageMult,
    calculateAppliedVolley,
)
from graphs.data.fitApplicationProfile.calc.launcher import (
    calcMissileFactor,
    calculateMissileRange,
    calculateRangeFactor as missileRangeFactor,
    calculateAppliedVolley as missileAppliedVolley,
    findBestCharge as missileFindBestCharge,
    volleyToDps as missileVolleyToDps,
)
from graphs.data.fitApplicationProfile.calc.optimize_ammo import (
    volleyToDps,
    findBestCharge,
    calculateTransitions,
    getVolleyAtDistance,
)
from graphs.data.fitApplicationProfile.calc.charges import (
    applyResists,
    filterChargesByQuality,
)

# turret.py
calcAngularSpeed = _turret_mod.calcAngularSpeed
calcTrackingFactor = _turret_mod.calcTrackingFactor
calcTurretDamageMult = _turret_mod.calcTurretDamageMult
calculateAppliedVolley = _turret_mod.calculateAppliedVolley

# launcher.py
calcMissileFactor = _launcher_mod.calcMissileFactor
calculateMissileRange = _launcher_mod.calculateMissileRange
missileRangeFactor = _launcher_mod.calculateRangeFactor
missileAppliedVolley = _launcher_mod.calculateAppliedVolley
missileFindBestCharge = _launcher_mod.findBestCharge
missileVolleyToDps = _launcher_mod.volleyToDps

# optimize_ammo.py
volleyToDps = _optimize_mod.volleyToDps
findBestCharge = _optimize_mod.findBestCharge
calculateTransitions = _optimize_mod.calculateTransitions
getVolleyAtDistance = _optimize_mod.getVolleyAtDistance

# charges.py
applyResists = _charges_mod.applyResists
filterChargesByQuality = _charges_mod.filterChargesByQuality


# =============================================================================
# turret.py — Angular Speed
# =============================================================================

class TestCalcAngularSpeed:

    def test_head_on_approach(self):
        # Both ships flying directly at each other (angle=0) → 0 transversal
        result = calcAngularSpeed(
            atkSpeed=1000, atkAngle=0, atkRadius=50,
            distance=10000,
            tgtSpeed=500, tgtAngle=0, tgtRadius=100)
        assert result == 0

    def test_pure_orbit(self):
        # Target orbiting at 90 degrees, attacker stationary
        result = calcAngularSpeed(
            atkSpeed=0, atkAngle=90, atkRadius=50,
            distance=10000,
            tgtSpeed=500, tgtAngle=90, tgtRadius=100)
        # transversal = |0*sin(90) - 500*sin(90)| = 500
        # ctc = 50 + 10000 + 100 = 10150
        expected = 500 / 10150
        assert result == pytest.approx(expected)

    def test_both_orbiting_same_direction(self):
        # Both at 90 degrees, same speed → transversal cancels
        result = calcAngularSpeed(
            atkSpeed=500, atkAngle=90, atkRadius=50,
            distance=10000,
            tgtSpeed=500, tgtAngle=90, tgtRadius=100)
        assert result == pytest.approx(0, abs=1e-10)

    def test_zero_distance(self):
        # distance=0, radii sum to ctcDistance
        result = calcAngularSpeed(
            atkSpeed=0, atkAngle=0, atkRadius=50,
            distance=0,
            tgtSpeed=500, tgtAngle=90, tgtRadius=100)
        expected = 500 / (50 + 100)
        assert result == pytest.approx(expected)

    def test_zero_ctc_with_transversal(self):
        # All radii and distance zero but nonzero transversal → inf
        result = calcAngularSpeed(
            atkSpeed=0, atkAngle=0, atkRadius=0,
            distance=0,
            tgtSpeed=500, tgtAngle=90, tgtRadius=0)
        assert result == math.inf

    def test_zero_ctc_zero_transversal(self):
        result = calcAngularSpeed(
            atkSpeed=0, atkAngle=0, atkRadius=0,
            distance=0,
            tgtSpeed=0, tgtAngle=0, tgtRadius=0)
        assert result == 0

    def test_none_distance(self):
        result = calcAngularSpeed(
            atkSpeed=1000, atkAngle=90, atkRadius=50,
            distance=None,
            tgtSpeed=500, tgtAngle=90, tgtRadius=100)
        assert result == 0


# =============================================================================
# turret.py — Tracking Factor
# =============================================================================

class TestCalcTrackingFactor:

    def test_stationary_target(self):
        # angularSpeed=0 → perfect tracking
        result = calcTrackingFactor(
            tracking=0.05, optimalSigRadius=40000,
            angularSpeed=0, tgtSigRadius=125)
        assert result == 1.0

    def test_zero_tracking(self):
        result = calcTrackingFactor(
            tracking=0, optimalSigRadius=40000,
            angularSpeed=0.01, tgtSigRadius=125)
        assert result == 0

    def test_zero_sig_radius(self):
        result = calcTrackingFactor(
            tracking=0.05, optimalSigRadius=40000,
            angularSpeed=0.01, tgtSigRadius=0)
        assert result == 0

    def test_known_formula(self):
        # 0.5 ^ ((angular * sigRes / (tracking * tgtSig)) ^ 2)
        tracking = 0.05
        sigRes = 40000
        angular = 0.01
        tgtSig = 125
        exponent = (angular * sigRes) / (tracking * tgtSig)
        expected = 0.5 ** (exponent ** 2)
        result = calcTrackingFactor(tracking, sigRes, angular, tgtSig)
        assert result == pytest.approx(expected)

    def test_large_sig_easy_tracking(self):
        # Battleship sig (400m) with fast tracking → near 1.0
        result = calcTrackingFactor(
            tracking=0.2, optimalSigRadius=40000,
            angularSpeed=0.001, tgtSigRadius=400)
        assert result > 0.99


# =============================================================================
# turret.py — Turret Damage Multiplier
# =============================================================================

class TestCalcTurretDamageMult:

    def test_perfect_hit(self):
        # cth=1.0 → full damage
        result = calcTurretDamageMult(1.0)
        assert result == pytest.approx(1.0)

    def test_zero_chance(self):
        # cth=0 → zero damage
        result = calcTurretDamageMult(0)
        assert result == 0

    def test_50pct_chance(self):
        # cth=0.5: wrecking = min(0.5, 0.01) = 0.01, wreckingPart = 0.03
        # normalChance = 0.49, avgDamage = (0.01+0.5)/2 + 0.49 = 0.745
        # normalPart = 0.49 * 0.745 = 0.36505
        # total = 0.36505 + 0.03 = 0.39505
        result = calcTurretDamageMult(0.5)
        expected = 0.49 * ((0.01 + 0.5) / 2 + 0.49) + 0.01 * 3
        assert result == pytest.approx(expected)

    def test_wrecking_only(self):
        # Very low cth (0.005) → only wrecking shots
        result = calcTurretDamageMult(0.005)
        # wreckingChance = 0.005, wreckingPart = 0.015
        # normalChance = 0, normalPart = 0
        assert result == pytest.approx(0.015)

    def test_monotonically_increasing(self):
        # Damage mult should increase with chance to hit
        prev = 0
        for cth_pct in range(0, 101, 5):
            cth = cth_pct / 100
            result = calcTurretDamageMult(cth)
            assert result >= prev
            prev = result


# =============================================================================
# turret.py — calculateAppliedVolley (integration of turret math)
# =============================================================================

class TestTurretAppliedVolley:

    def _make_charge_data(self, raw_volley=100, optimal=20000, falloff=10000, tracking=0.05):
        return {
            'name': 'TestAmmo',
            'raw_volley': raw_volley,
            'effective_optimal': optimal,
            'effective_falloff': falloff,
            'effective_tracking': tracking,
        }

    def _make_turret_base(self, sig_res=40000):
        return {'optimalSigRadius': sig_res}

    def _make_tracking_params(self, tgt_speed=0, tgt_angle=90, tgt_sig=400,
                               atk_speed=0, atk_angle=0, atk_radius=50, tgt_radius=100):
        return {
            'atkSpeed': atk_speed, 'atkAngle': atk_angle, 'atkRadius': atk_radius,
            'tgtSpeed': tgt_speed, 'tgtAngle': tgt_angle, 'tgtRadius': tgt_radius,
            'tgtSigRadius': tgt_sig,
        }

    def test_point_blank_stationary(self):
        # At 0km, stationary target → full damage
        cd = self._make_charge_data(raw_volley=100, optimal=20000, falloff=10000)
        tb = self._make_turret_base()
        tp = self._make_tracking_params(tgt_speed=0)
        result = calculateAppliedVolley(cd, 0, tb, tp)
        assert result == pytest.approx(100.0)

    def test_within_optimal(self):
        # Within optimal, stationary → full damage
        cd = self._make_charge_data(raw_volley=100, optimal=20000, falloff=10000)
        tb = self._make_turret_base()
        tp = self._make_tracking_params(tgt_speed=0)
        result = calculateAppliedVolley(cd, 15000, tb, tp)
        assert result == pytest.approx(100.0)

    def test_at_optimal_plus_falloff(self):
        # At optimal + falloff, range factor = 0.5^1 = 0.5
        cd = self._make_charge_data(raw_volley=100, optimal=20000, falloff=10000)
        tb = self._make_turret_base()
        tp = self._make_tracking_params(tgt_speed=0)
        result = calculateAppliedVolley(cd, 30000, tb, tp)
        # range_factor = 0.5 ^ ((10000/10000)^2) = 0.5
        # damage_mult from cth=0.5 (see TestCalcTurretDamageMult)
        expected_damage_mult = calcTurretDamageMult(0.5)
        assert result == pytest.approx(100.0 * expected_damage_mult)

    def test_no_tracking_params(self):
        # trackingParams=None → perfect tracking (factor=1.0)
        cd = self._make_charge_data(raw_volley=100, optimal=20000, falloff=10000)
        tb = self._make_turret_base()
        result = calculateAppliedVolley(cd, 15000, tb, None)
        assert result == pytest.approx(100.0)

    def test_far_beyond_range(self):
        # Way past falloff → near-zero damage
        cd = self._make_charge_data(raw_volley=100, optimal=10000, falloff=5000)
        tb = self._make_turret_base()
        tp = self._make_tracking_params(tgt_speed=0)
        result = calculateAppliedVolley(cd, 50000, tb, tp)
        assert result < 1.0


# =============================================================================
# launcher.py — Missile Application Factor
# =============================================================================

class TestCalcMissileFactor:

    def test_perfect_application(self):
        # Large sig, slow target → 1.0
        result = calcMissileFactor(
            atkEr=50, atkEv=200, atkDrf=0.5,
            tgtSpeed=50, tgtSigRadius=400)
        assert result == 1.0

    def test_sig_limited(self):
        # Target sig smaller than explosion radius
        result = calcMissileFactor(
            atkEr=200, atkEv=200, atkDrf=0.5,
            tgtSpeed=0, tgtSigRadius=100)
        # min(1, 100/200) = 0.5 (speed term not limiting since tgtSpeed=0)
        assert result == pytest.approx(0.5)

    def test_speed_limited(self):
        # Fast target, good sig
        result = calcMissileFactor(
            atkEr=50, atkEv=100, atkDrf=0.5,
            tgtSpeed=1000, tgtSigRadius=400)
        # sig/eR = 400/50 = 8
        # ((100*400)/(50*1000))^0.5 = (0.8)^0.5 ≈ 0.894
        # min(1, 8, 0.894) = 0.894
        expected = ((100 * 400) / (50 * 1000)) ** 0.5
        assert result == pytest.approx(expected)

    def test_stationary_target(self):
        # tgtSpeed=0, speed term not evaluated
        result = calcMissileFactor(
            atkEr=50, atkEv=200, atkDrf=0.5,
            tgtSpeed=0, tgtSigRadius=400)
        # min(1, 400/50) = min(1, 8) = 1.0
        assert result == 1.0

    def test_zero_explosion_radius(self):
        result = calcMissileFactor(
            atkEr=0, atkEv=200, atkDrf=0.5,
            tgtSpeed=100, tgtSigRadius=400)
        # No sig or speed terms added, min(1) = 1.0
        assert result == 1.0


# =============================================================================
# launcher.py — Missile Range
# =============================================================================

class TestCalculateMissileRange:

    def test_instant_acceleration(self):
        # If accelTime >= flightTime, all time is acceleration
        # accelTime = min(10, 1000 * 1000 / 1e6) = min(10, 1) = 1
        # duringAccel = 5000/2 * 1 = 2500
        # fullSpeed = 5000 * (10 - 1) = 45000
        # total = 47500
        result = calculateMissileRange(
            maxVelocity=5000, mass=1000, agility=1000, flightTime=10)
        assert result == pytest.approx(47500)

    def test_zero_flight_time(self):
        result = calculateMissileRange(
            maxVelocity=5000, mass=1000, agility=1000, flightTime=0)
        assert result == 0

    def test_all_acceleration(self):
        # accelTime = min(1, 5000 * 5000 / 1e6) = min(1, 25) = 1
        # duringAccel = 5000/2 * 1 = 2500
        # fullSpeed = 5000 * 0 = 0
        result = calculateMissileRange(
            maxVelocity=5000, mass=5000, agility=5000, flightTime=1)
        assert result == pytest.approx(2500)

    def test_negligible_acceleration(self):
        # Very light missile: accelTime ≈ 0
        # accelTime = min(10, 1 * 1 / 1e6) ≈ 0
        # Nearly all at full speed
        result = calculateMissileRange(
            maxVelocity=5000, mass=1, agility=1, flightTime=10)
        assert result == pytest.approx(50000, rel=0.01)


# =============================================================================
# launcher.py — Missile Range Factor
# =============================================================================

class TestMissileRangeFactor:

    def test_within_lower_range(self):
        assert missileRangeFactor(5000, 10000, 15000, 0.3) == 1.0

    def test_at_lower_range(self):
        assert missileRangeFactor(10000, 10000, 15000, 0.3) == 1.0

    def test_between_ranges(self):
        # Between lower and higher → higherChance
        assert missileRangeFactor(12000, 10000, 15000, 0.3) == 0.3

    def test_beyond_higher_range(self):
        assert missileRangeFactor(20000, 10000, 15000, 0.3) == 0.0

    def test_at_higher_range(self):
        assert missileRangeFactor(15000, 10000, 15000, 0.3) == 0.3


# =============================================================================
# launcher.py — Missile Applied Volley
# =============================================================================

class TestMissileAppliedVolley:

    def _make_charge_data(self, raw_volley=100, lower=20000, higher=25000,
                           higher_chance=0.5, er=50, ev=200, drf=0.5):
        return {
            'name': 'TestMissile',
            'raw_volley': raw_volley,
            'lowerRange': lower,
            'higherRange': higher,
            'higherChance': higher_chance,
            'explosionRadius': er,
            'explosionVelocity': ev,
            'damageReductionFactor': drf,
        }

    def test_in_range_perfect_app(self):
        cd = self._make_charge_data(raw_volley=100, lower=20000, higher=25000)
        # Distance within lower range, big slow target
        result = missileAppliedVolley(cd, 10000, tgtSpeed=50, tgtSigRadius=400)
        assert result == pytest.approx(100.0)

    def test_out_of_range(self):
        cd = self._make_charge_data(raw_volley=100, lower=20000, higher=25000)
        result = missileAppliedVolley(cd, 30000, tgtSpeed=50, tgtSigRadius=400)
        assert result == 0

    def test_partial_range(self):
        cd = self._make_charge_data(raw_volley=100, lower=20000, higher=25000, higher_chance=0.4)
        result = missileAppliedVolley(cd, 22000, tgtSpeed=50, tgtSigRadius=400)
        # Between ranges → rangeFactor = 0.4, perfect app → 100 * 0.4 = 40
        assert result == pytest.approx(40.0)


# =============================================================================
# optimize_ammo.py — volleyToDps
# =============================================================================

class TestVolleyToDps:

    def test_normal(self):
        assert volleyToDps(1000, 5000) == pytest.approx(200)

    def test_zero_cycle(self):
        assert volleyToDps(1000, 0) == 0

    def test_negative_cycle(self):
        assert volleyToDps(1000, -1) == 0


# =============================================================================
# optimize_ammo.py — findBestCharge (turret version)
# =============================================================================

class TestFindBestCharge:

    def _make_turret_base(self):
        return {'optimalSigRadius': 40000}

    def test_single_charge(self):
        charges = [{
            'name': 'Multifrequency', 'raw_volley': 100,
            'effective_optimal': 10000, 'effective_falloff': 5000,
            'effective_tracking': 0.05,
        }]
        volley, name, idx = findBestCharge(charges, 5000, self._make_turret_base(), None)
        assert name == 'Multifrequency'
        assert idx == 0
        assert volley > 0

    def test_short_vs_long_range_ammo(self):
        # At close range, high-damage short-range ammo wins
        short_range = {
            'name': 'Multifrequency', 'raw_volley': 150,
            'effective_optimal': 5000, 'effective_falloff': 3000,
            'effective_tracking': 0.04,
        }
        long_range = {
            'name': 'Radio', 'raw_volley': 50,
            'effective_optimal': 20000, 'effective_falloff': 8000,
            'effective_tracking': 0.08,
        }
        charges = [short_range, long_range]
        volley, name, idx = findBestCharge(charges, 1000, self._make_turret_base(), None)
        assert name == 'Multifrequency'

    def test_long_range_wins_at_distance(self):
        short_range = {
            'name': 'Multifrequency', 'raw_volley': 150,
            'effective_optimal': 5000, 'effective_falloff': 3000,
            'effective_tracking': 0.04,
        }
        long_range = {
            'name': 'Radio', 'raw_volley': 50,
            'effective_optimal': 20000, 'effective_falloff': 8000,
            'effective_tracking': 0.08,
        }
        charges = [short_range, long_range]
        # At 25km, Multifrequency is way past falloff, Radio is within optimal
        volley, name, idx = findBestCharge(charges, 25000, self._make_turret_base(), None)
        assert name == 'Radio'


# =============================================================================
# optimize_ammo.py — calculateTransitions
# =============================================================================

class TestCalculateTransitions:

    def _make_turret_base(self):
        return {'optimalSigRadius': 40000}

    def _empty_projected_cache(self):
        return {'hasProjected': False, 'baseTgtSpeed': 0, 'baseTgtSigRadius': 400}

    def test_single_charge_no_transitions(self):
        charges = [{
            'name': 'Multifrequency', 'raw_volley': 100,
            'effective_optimal': 20000, 'effective_falloff': 10000,
            'effective_tracking': 0.05,
        }]
        transitions = calculateTransitions(
            charges, self._make_turret_base(), None,
            self._empty_projected_cache(), maxDistance=50000, resolution=1000)
        # Only the initial entry at distance 0
        assert len(transitions) == 1
        assert transitions[0][0] == 0
        assert transitions[0][2] == 'Multifrequency'

    def test_two_charges_has_transition(self):
        short = {
            'name': 'Multifrequency', 'raw_volley': 150,
            'effective_optimal': 5000, 'effective_falloff': 3000,
            'effective_tracking': 0.05,
        }
        long = {
            'name': 'Radio', 'raw_volley': 50,
            'effective_optimal': 25000, 'effective_falloff': 10000,
            'effective_tracking': 0.08,
        }
        transitions = calculateTransitions(
            [short, long], self._make_turret_base(), None,
            self._empty_projected_cache(), maxDistance=50000, resolution=500)

        # Should start with short-range ammo, transition to long-range
        assert transitions[0][2] == 'Multifrequency'
        assert len(transitions) >= 2
        # Find the transition to Radio
        radio_transitions = [t for t in transitions if t[2] == 'Radio']
        assert len(radio_transitions) >= 1
        # Transition should be somewhere between 5km and 25km
        assert 5000 <= radio_transitions[0][0] <= 25000

    def test_empty_charges(self):
        transitions = calculateTransitions(
            [], self._make_turret_base(), None,
            self._empty_projected_cache(), maxDistance=50000)
        assert transitions == []

    def test_transitions_sorted_ascending(self):
        short = {
            'name': 'Multifrequency', 'raw_volley': 150,
            'effective_optimal': 5000, 'effective_falloff': 3000,
            'effective_tracking': 0.05,
        }
        long = {
            'name': 'Radio', 'raw_volley': 50,
            'effective_optimal': 25000, 'effective_falloff': 10000,
            'effective_tracking': 0.08,
        }
        transitions = calculateTransitions(
            [short, long], self._make_turret_base(), None,
            self._empty_projected_cache(), maxDistance=50000, resolution=500)
        distances = [t[0] for t in transitions]
        assert distances == sorted(distances)


# =============================================================================
# optimize_ammo.py — getVolleyAtDistance
# =============================================================================

class TestGetVolleyAtDistance:

    def _make_turret_base(self):
        return {'optimalSigRadius': 40000}

    def _empty_projected_cache(self):
        return {'hasProjected': False, 'baseTgtSpeed': 0, 'baseTgtSigRadius': 400}

    def test_returns_correct_charge(self):
        short = {
            'name': 'Multifrequency', 'raw_volley': 150,
            'effective_optimal': 5000, 'effective_falloff': 3000,
            'effective_tracking': 0.05,
        }
        long = {
            'name': 'Radio', 'raw_volley': 50,
            'effective_optimal': 25000, 'effective_falloff': 10000,
            'effective_tracking': 0.08,
        }
        charges = [short, long]
        transitions = calculateTransitions(
            charges, self._make_turret_base(), None,
            self._empty_projected_cache(), maxDistance=50000, resolution=500)

        # At 1km, should use Multifrequency
        volley, name = getVolleyAtDistance(
            transitions, charges, self._make_turret_base(), 1000,
            None, self._empty_projected_cache())
        assert name == 'Multifrequency'
        assert volley > 0

    def test_empty_transitions(self):
        volley, name = getVolleyAtDistance(
            [], [], self._make_turret_base(), 1000,
            None, self._empty_projected_cache())
        assert volley == 0
        assert name is None


# =============================================================================
# charges.py — applyResists
# =============================================================================

class TestApplyResists:

    def test_no_resists(self):
        stats = {
            'emDamage': 100, 'thermalDamage': 50,
            'kineticDamage': 30, 'explosiveDamage': 20,
            'totalDamage': 200,
        }
        result = applyResists(stats, None)
        assert result['totalDamage'] == 200

    def test_uniform_50pct(self):
        stats = {
            'emDamage': 100, 'thermalDamage': 100,
            'kineticDamage': 100, 'explosiveDamage': 100,
            'totalDamage': 400,
        }
        result = applyResists(stats, (0.5, 0.5, 0.5, 0.5))
        assert result['totalDamage'] == pytest.approx(200)
        assert result['emDamage'] == pytest.approx(50)

    def test_full_resist(self):
        stats = {
            'emDamage': 100, 'thermalDamage': 100,
            'kineticDamage': 100, 'explosiveDamage': 100,
            'totalDamage': 400,
        }
        result = applyResists(stats, (1.0, 1.0, 1.0, 1.0))
        assert result['totalDamage'] == pytest.approx(0)

    def test_mixed_resists(self):
        stats = {
            'emDamage': 100, 'thermalDamage': 100,
            'kineticDamage': 100, 'explosiveDamage': 100,
            'totalDamage': 400,
        }
        result = applyResists(stats, (0.8, 0.6, 0.4, 0.2))
        assert result['emDamage'] == pytest.approx(20)
        assert result['thermalDamage'] == pytest.approx(40)
        assert result['kineticDamage'] == pytest.approx(60)
        assert result['explosiveDamage'] == pytest.approx(80)
        assert result['totalDamage'] == pytest.approx(200)

    def test_does_not_mutate_input(self):
        stats = {
            'emDamage': 100, 'thermalDamage': 100,
            'kineticDamage': 100, 'explosiveDamage': 100,
            'totalDamage': 400,
        }
        applyResists(stats, (0.5, 0.5, 0.5, 0.5))
        assert stats['totalDamage'] == 400


# =============================================================================
# charges.py — filterChargesByQuality (with mock charges)
# =============================================================================

class MockMetaGroup:
    def __init__(self, id):
        self.ID = id


class MockCharge:
    def __init__(self, name, meta_group_id):
        self.name = name
        self.metaGroup = MockMetaGroup(meta_group_id) if meta_group_id else None


class TestFilterChargesByQuality:

    def _make_charges(self):
        return [
            MockCharge('Multifrequency S', 1),          # T1
            MockCharge('Conflagration S', 2),            # T2
            MockCharge('Imperial Navy Multifrequency S', 4),  # Navy faction
            MockCharge('True Sansha Multifrequency S', 4),    # Pirate faction
        ]

    def test_all_tier(self):
        charges = self._make_charges()
        result = filterChargesByQuality(charges, 'all')
        assert len(result) == 4

    def test_t1_tier(self):
        charges = self._make_charges()
        result = filterChargesByQuality(charges, 't1')
        names = [c.name for c in result]
        assert 'Multifrequency S' in names
        assert 'Conflagration S' in names  # T2 always included
        assert 'Imperial Navy Multifrequency S' not in names
        assert 'True Sansha Multifrequency S' not in names

    def test_navy_tier(self):
        charges = self._make_charges()
        result = filterChargesByQuality(charges, 'navy')
        names = [c.name for c in result]
        assert 'Multifrequency S' in names
        assert 'Conflagration S' in names
        assert 'Imperial Navy Multifrequency S' in names
        assert 'True Sansha Multifrequency S' not in names

    def test_navy_tier_capital_ammo(self):
        charges = [
            MockCharge('Multifrequency XL', 1),
            MockCharge('Sansha Multifrequency XL', 4),   # Pirate = "navy" for capitals
            MockCharge('Dark Blood Multifrequency XL', 4),  # High-tier pirate
        ]
        result = filterChargesByQuality(charges, 'navy')
        names = [c.name for c in result]
        assert 'Multifrequency XL' in names
        assert 'Sansha Multifrequency XL' in names
        assert 'Dark Blood Multifrequency XL' not in names

    def test_empty_filter_returns_all(self):
        # If filtering produces nothing, return all charges as fallback
        charges = [MockCharge('Dark Blood Multifrequency S', 4)]
        result = filterChargesByQuality(charges, 't1')
        assert len(result) == 1  # Fallback: returns all


# =============================================================================
# launcher.py — missile findBestCharge with damage priority tiebreak
# =============================================================================

class TestMissileFindBestCharge:

    def test_tiebreak_damage_priority(self):
        # Two missiles with identical stats but different damage types
        # EM (Mjolnir) should win over Thermal (Inferno) as tiebreak
        em_missile = {
            'name': 'Mjolnir', 'raw_volley': 100,
            'lowerRange': 20000, 'higherRange': 25000,
            'higherChance': 0.5, 'explosionRadius': 50,
            'explosionVelocity': 200, 'damageReductionFactor': 0.5,
            'damage_priority': 0,  # EM = highest priority
        }
        thermal_missile = {
            'name': 'Inferno', 'raw_volley': 100,
            'lowerRange': 20000, 'higherRange': 25000,
            'higherChance': 0.5, 'explosionRadius': 50,
            'explosionVelocity': 200, 'damageReductionFactor': 0.5,
            'damage_priority': 1,  # Thermal = lower priority
        }
        volley, name, idx = missileFindBestCharge(
            [thermal_missile, em_missile], 10000,
            tgtSpeed=100, tgtSigRadius=400)
        assert name == 'Mjolnir'
