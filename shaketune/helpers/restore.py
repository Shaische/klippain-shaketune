# Shake&Tune: 3D printer analysis tools
#
# Licensed under the GNU General Public License v3.0 (GPL-3.0)
#
# File: restore.py
# Description: RapidPlacer patch — put the machine back to its normal motion settings after a test.
#              The test commands raise the acceleration limit and switch input shaping off while
#              they shake the machine. Upstream restores both only at the end of a successful run,
#              so any error part-way (a missing accelerometer, a Klipper error, an emergency stop)
#              left Klipper at test settings until the next restart. Each command now calls this
#              from a `finally:` block.


def restore_motion_settings(gcode, input_shaper, old_accel, old_mcr=None, old_sqv=None) -> None:
    """Re-enable input shaping (if the test turned it off) and put back the
    acceleration limit, minimum cruise ratio and square-corner velocity.

    Every step is on its own and never raises: after an emergency stop Klipper
    is shut down and refuses commands — it reloads its config when restarted —
    and a failure here must not hide the error that ended the test.
    """
    if input_shaper is not None:
        try:
            input_shaper.enable_shaping()  # no-op when shaping wasn't disabled
        except Exception:
            pass
    parts = [f'ACCEL={old_accel}']
    if old_mcr is not None:  # minimum_cruise_ratio found: Klipper >= v0.12.0-239
        parts.append(f'MINIMUM_CRUISE_RATIO={old_mcr}')
    if old_sqv is not None:
        parts.append(f'SQUARE_CORNER_VELOCITY={old_sqv}')
    try:
        gcode.run_script_from_command('SET_VELOCITY_LIMIT ' + ' '.join(parts))
    except Exception:
        pass
