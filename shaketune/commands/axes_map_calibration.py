# Shake&Tune: 3D printer analysis tools
#
# Copyright (C) 2024 Félix Boisselier <felix@fboisselier.fr> (Frix_x on Discord)
# Licensed under the GNU General Public License v3.0 (GPL-3.0)
#
# File: axes_map_calibration.py
# Description: Provides a command for calibrating the axes map of a 3D printer using an accelerometer.
#              The script moves the printer head along specified axes, starts and stops measurements,
#              and performs post-processing to analyze the collected data.

from datetime import datetime

from ..helpers.accelerometer import Accelerometer, MeasurementsManager
from ..helpers.console_output import ConsoleOutput
from ..shaketune_process import ShakeTuneProcess

SEGMENT_LENGTH = 30  # mm


def axes_map_calibration(gcmd, config, st_process: ShakeTuneProcess) -> None:
    date = datetime.now().strftime('%Y%m%d_%H%M%S')

    z_height = gcmd.get_float('Z_HEIGHT', default=20.0)
    speed = gcmd.get_float('SPEED', default=80.0, minval=20.0)
    accel = gcmd.get_int('ACCEL', default=1500, minval=100)
    feedrate_travel = gcmd.get_float('TRAVEL_SPEED', default=120.0, minval=20.0)

    printer = config.get_printer()
    gcode = printer.lookup_object('gcode')
    toolhead = printer.lookup_object('toolhead')
    systime = printer.get_reactor().monotonic()

    accel_chip = Accelerometer.find_axis_accelerometer(printer, 'xy')
    k_accelerometer = printer.lookup_object(accel_chip, None)
    if k_accelerometer is None:
        raise gcmd.error('Multi-accelerometer configurations are not supported for this macro!')
    pconfig = printer.lookup_object('configfile')
    current_axes_map = pconfig.status_raw_config[accel_chip].get('axes_map', None)
    accelerometer = Accelerometer(k_accelerometer, printer.get_reactor())

    toolhead_info = toolhead.get_status(systime)
    old_accel = toolhead_info['max_accel']
    old_sqv = toolhead_info['square_corner_velocity']

    # set the wanted acceleration values
    if 'minimum_cruise_ratio' in toolhead_info:
        old_mcr = toolhead_info['minimum_cruise_ratio']  # minimum_cruise_ratio found: Klipper >= v0.12.0-239
        gcode.run_script_from_command(
            f'SET_VELOCITY_LIMIT ACCEL={accel} MINIMUM_CRUISE_RATIO=0 SQUARE_CORNER_VELOCITY=5.0'
        )
    else:  # minimum_cruise_ratio not found: Klipper < v0.12.0-239
        old_mcr = None
        gcode.run_script_from_command(f'SET_VELOCITY_LIMIT ACCEL={accel} SQUARE_CORNER_VELOCITY=5.0')

    # Deactivate input shaper if it is active to get raw movements
    input_shaper = printer.lookup_object('input_shaper', None)
    if input_shaper is not None:
        input_shaper.disable_shaping()
    else:
        input_shaper = None

    kin_info = toolhead.kin.get_status(systime)
    mid_x = (kin_info['axis_minimum'].x + kin_info['axis_maximum'].x) / 2
    mid_y = (kin_info['axis_minimum'].y + kin_info['axis_maximum'].y) / 2
    pos = list(toolhead.get_position())  # custom Klipper may return >4 axes (e.g. XYZABCD)

    # RapidPlacer patch: the fake Z stepper is never homed by G28 (only X/Y are real).
    # Tell Klipper Z is at 0 so toolhead.move() doesn't reject the command.
    gcode.run_script_from_command('SET_KINEMATIC_POSITION Z=0')

    # Going to the start position — only change XY, keep Z at 0 (fake axis)
    pos[0], pos[1], pos[2] = mid_x - SEGMENT_LENGTH / 2, mid_y - SEGMENT_LENGTH / 2, 0
    toolhead.move(pos, feedrate_travel)
    toolhead.dwell(0.5)

    creator = st_process.get_graph_creator()
    filename = creator.get_folder() / f'{creator.get_type().replace(" ", "")}_{date}'
    measurements_manager = MeasurementsManager(st_process.get_st_config().chunk_size, printer.get_reactor(), filename)

    # Start the measurements and do the movements (+X, +Y and then +Z)
    accelerometer.start_recording(measurements_manager, name='axesmap_X', append_time=True)
    toolhead.dwell(0.5)
    pos[0], pos[1] = mid_x + SEGMENT_LENGTH / 2, mid_y - SEGMENT_LENGTH / 2
    toolhead.move(pos, speed)
    toolhead.dwell(0.5)
    accelerometer.stop_recording()
    toolhead.dwell(0.5)
    accelerometer.start_recording(measurements_manager, name='axesmap_Y', append_time=True)
    toolhead.dwell(0.5)
    pos[0], pos[1] = mid_x + SEGMENT_LENGTH / 2, mid_y + SEGMENT_LENGTH / 2
    toolhead.move(pos, speed)
    toolhead.dwell(0.5)
    accelerometer.stop_recording()
    toolhead.dwell(0.5)
    # RapidPlacer patch: Z axis uses manual_stepper left_z (nozzle on head),
    # not the fake toolhead Z. The nozzle motor is on the head PCB next to
    # the ADXL, so its vibration will be detected by the accelerometer.
    z_stepper_name = gcmd.get('Z_STEPPER', default='left_z')
    z_gcode_axis = gcmd.get('Z_GCODE_AXIS', default='A')
    z_speed = gcmd.get_float('Z_SPEED', default=50.0)  # match macros.cfg homing speed
    z_move_distance = min(15.0, SEGMENT_LENGTH)  # nozzle range is ~22mm, use 15mm

    # Unregister from G-code axis (required before MANUAL_STEPPER moves)
    gcode.run_script_from_command(
        f'MANUAL_STEPPER STEPPER={z_stepper_name} GCODE_AXIS='
    )
    gcode.run_script_from_command(
        f'MANUAL_STEPPER STEPPER={z_stepper_name} SET_POSITION=21.9'
    )
    toolhead.dwell(0.3)
    accelerometer.start_recording(measurements_manager, name='axesmap_Z', append_time=True)
    toolhead.dwell(0.5)
    gcode.run_script_from_command(
        f'MANUAL_STEPPER STEPPER={z_stepper_name} MOVE={21.9 - z_move_distance} SPEED={z_speed}'
    )
    toolhead.dwell(0.5)
    accelerometer.stop_recording()
    toolhead.dwell(0.3)
    # Return nozzle to home position and re-register as G-code axis
    gcode.run_script_from_command(
        f'MANUAL_STEPPER STEPPER={z_stepper_name} MOVE=21.9 SPEED={z_speed}'
    )
    gcode.run_script_from_command(
        f'MANUAL_STEPPER STEPPER={z_stepper_name} GCODE_AXIS={z_gcode_axis}'
    )
    toolhead.dwell(0.5)

    # Re-enable the input shaper if it was active
    if input_shaper is not None:
        input_shaper.enable_shaping()

    # Restore the previous acceleration values
    if old_mcr is not None:  # minimum_cruise_ratio found: Klipper >= v0.12.0-239
        gcode.run_script_from_command(
            f'SET_VELOCITY_LIMIT ACCEL={old_accel} MINIMUM_CRUISE_RATIO={old_mcr} SQUARE_CORNER_VELOCITY={old_sqv}'
        )
    else:  # minimum_cruise_ratio not found: Klipper < v0.12.0-239
        gcode.run_script_from_command(f'SET_VELOCITY_LIMIT ACCEL={old_accel} SQUARE_CORNER_VELOCITY={old_sqv}')

    toolhead.wait_moves()

    # Run post-processing
    ConsoleOutput.print('Analysis of the movements...')
    ConsoleOutput.print('This may take some time (1-3min)')
    creator.configure(accel, current_axes_map)
    creator.define_output_target(filename)
    measurements_manager.save_stdata()
    st_process.run(filename)
    st_process.wait_for_completion()
