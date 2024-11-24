#!/usr/bin/env python3

__copyright__ = "Copyright 2024, Paul Wichern"

import adsk.core, adsk.fusion, adsk.cam, traceback, json

def load_file(ui):
    # File selection dialog
    fileDialog = ui.createFileDialog()
    fileDialog.isMultiSelectEnabled = False
    fileDialog.title = "Select a File"
    fileDialog.filter = "All Files (*.*)"
    dialogResult = fileDialog.showOpen()
    
    # Check if the user canceled the dialog
    if dialogResult != adsk.core.DialogResults.DialogOK:
        return None
    
    # Get the selected file path
    with open(fileDialog.filename, 'r') as json_in:
        return json.load(json_in)

def read_json(file_path):
    """Reads polylines from the JSON file."""
    with open(file_path, 'r') as file:
        data = json.load(file)
    return data['polylines']

def create_sketch_from_polyline(sketch, polyline, offset, scale):
    """Creates a sketch based on the polyline data."""
    points = [adsk.core.Point3D.create((p[0] - offset[0]) * scale[0], (p[1] - offset[1]) * scale[1], 0) for p in polyline]
    for i in range(len(points) - 1):
        sketch.sketchCurves.sketchLines.addByTwoPoints(points[i], points[i + 1])
    # Optionally close the polyline if it's a loop
    if points[0].isEqualTo(points[-1]):
        sketch.sketchCurves.sketchLines.addByTwoPoints(points[-1], points[0])

def create_extrusion(root_comp, sketch, height, operation = adsk.fusion.FeatureOperations.NewBodyFeatureOperation):
    """Creates an extrusion from the sketch."""
    prof = sketch.profiles.item(0)
    extrudes = root_comp.features.extrudeFeatures
    ext_input = extrudes.createInput(prof, operation)
    distance = adsk.core.ValueInput.createByReal(height)
    ext_input.setDistanceExtent(False, distance)
    extrudes.add(ext_input)

def run(context):
    ui = None
    try:
        # Get the application and user interface
        app = adsk.core.Application.get()
        ui = app.userInterface

        data = load_file(ui)
        offset = [data['metadata']['x_min'], data['metadata']['y_min']]
        scale = [data['metadata']['x_scale'], data['metadata']['y_scale']]

        # Get the active design
        design = app.activeProduct
        if not design:
            ui.messageBox('No active Fusion 360 design found.')
            return
        
        # Get the root component of the active design
        rootComp = design.rootComponent
        sketches = rootComp.sketches
        xyPlane = rootComp.xYConstructionPlane

        # Create base square
        sketch = sketches.add(xyPlane)
        sketch.name = f'Geotile base ({data['metadata']['x_min']:.4f} {data['metadata']['y_min']:.4f})'
        point1 = adsk.core.Point3D.create(0, 0, 0)
        point2 = adsk.core.Point3D.create(10, 10, 0)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(point1, point2)
        create_extrusion(rootComp, sketch, 1)

        # Create elevations
        elevation_sketches = dict()

        for feature in data['features']:
            if 'elevation_min' in feature['properties']:
                # Get sketch
                elevation_max = float(feature['properties']['elevation_max'])
                sketch = elevation_sketches.get(elevation_max, sketches.add(xyPlane))
                sketch.name = f'Geotile elevation {elevation_max}'
                elevation_sketches[elevation_max] = sketch

                if feature['geometry']['type'] == 'MultiPolygon':
                    for polygon in feature['geometry']['coordinates']:
                        for p in polygon:
                            create_sketch_from_polyline(sketch, p, offset, scale)
                            
                else:
                    ui.messageBox(f'Unexpected feature geometry type: {feature['geometry']['type']}')
        

        for elevation_max, sk in elevation_sketches.items():
            create_extrusion(rootComp, sk, elevation_max/100, adsk.fusion.FeatureOperations.JoinFeatureOperation)

        ui.messageBox('done')

    except:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
