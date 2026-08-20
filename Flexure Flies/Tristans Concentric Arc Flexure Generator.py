#Author-Tristan
#Description-Create a concentric disk flexure based on staggered arc cuts with customizable sweep angles.

import adsk.core, adsk.fusion, adsk.cam, traceback, math

def run(context):
    ui = None
    try:
        # boilerplate API stuff
        app = adsk.core.Application.get()
        ui  = app.userInterface
        design = app.activeProduct
        rootComp = design.rootComponent

        # --- CUSTOMIZABLE PARAMETERS ---
        numCutsPerRing = 3
        numRings = 3
        
        # Set the length of the cuts (in degrees) for the [Inner, Middle, Outer] rings
        sweepAnglesDeg = [75.0, 90.0, 80.0] 
        
        # Dimensions (Fusion API uses centimeters natively)
        slotWidth = 0.01 * 2.54       # 0.01 inches converted to cm
        stockThickness = 0.01 * 2.54  # 0.01 inches converted to cm
        
        outerRadius = 6.0 / 2.0       # 60mm OD (3cm radius)
        innerRadius = 3.2 / 10.0      # ~1/8in hole, adjust as needed
        outerRingWidth = 6.0 / 10.0   # Solid outer perimeter
        innerRingWidth = 4.0 / 10.0   # Solid inner perimeter

        # --- SKETCH SETUP ---
        sketches = rootComp.sketches
        xyPlane = rootComp.xYConstructionPlane
        
        beamSketch = sketches.add(xyPlane)
        beamSketch.isVisible = False
        beamSketch.name = 'arc_cuts'
        
        endFilletSketch = sketches.add(xyPlane)
        endFilletSketch.isVisible = False
        endFilletSketch.name = 'end_fillets'

        # --- CALCULATE RADII FOR THE 3 RINGS ---
        innerCutLimit = innerRadius + innerRingWidth
        outerCutLimit = outerRadius - outerRingWidth
        availableSpace = outerCutLimit - innerCutLimit
        
        # Distribute the 3 rings evenly across the available space
        radii = [
            innerCutLimit,
            innerCutLimit + (availableSpace * 0.5),
            innerCutLimit + availableSpace
        ]

        centerPt = adsk.core.Point3D.create(0, 0, 0)

        # --- GENERATE THE CURVES ---
        for ringIdx in range(numRings):
            r = radii[ringIdx]
            sweepRad = sweepAnglesDeg[ringIdx] * math.pi / 180.0
            
            # Stagger alternating rings (offset by half the spacing between cuts)
            angleSpacing = (2 * math.pi) / numCutsPerRing
            baseOffset = angleSpacing / 2.0 if ringIdx % 2 != 0 else 0.0
            
            for cutIdx in range(numCutsPerRing):
                # Calculate the center point of this specific cut
                centerAngle = baseOffset + (cutIdx * angleSpacing)
                
                # Start angle of the arc
                startAngle = centerAngle - (sweepRad / 2.0)
                startX = r * math.cos(startAngle)
                startY = r * math.sin(startAngle)
                startPt = adsk.core.Point3D.create(startX, startY, 0)
                
                # Draw the arc
                beamSketch.sketchCurves.sketchArcs.addByCenterStartSweep(centerPt, startPt, sweepRad)
                
                # Calculate end point for the fillet
                endAngle = startAngle + sweepRad
                endX = r * math.cos(endAngle)
                endY = r * math.sin(endAngle)
                endPt = adsk.core.Point3D.create(endX, endY, 0)
                
                # Draw the stress-relief circles (fillets) at both ends of the cut
                endFilletSketch.sketchCurves.sketchCircles.addByCenterRadius(startPt, 0.5 * slotWidth)
                endFilletSketch.sketchCurves.sketchCircles.addByCenterRadius(endPt, 0.5 * slotWidth)

        # --- EXTRUDE THE BASIC DISK ---
        diskSketch = sketches.add(xyPlane)
        diskSketch.isVisible = False
        diskSketch.name = 'disk'
        diskSketch.sketchCurves.sketchCircles.addByCenterRadius(centerPt, innerRadius)
        diskSketch.sketchCurves.sketchCircles.addByCenterRadius(centerPt, outerRadius)
        
        rootComp.features.extrudeFeatures.addSimple(
            diskSketch.profiles.item(1), 
            adsk.core.ValueInput.createByReal(stockThickness), 
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        )

        # --- THIN EXTRUDE THE ARC CUTS ---
        pros = []
        objs = adsk.core.ObjectCollection.create()
        for crv in beamSketch.sketchCurves:
            objs.clear()
            objs.add(crv)
            # Create an open profile for each arc so we can thin extrude it
            pros.append(rootComp.createOpenProfile(objs, False))

        for profile in pros:
            thinExtrude(
                profile, 
                slotWidth, 
                stockThickness, 
                adsk.fusion.ThinExtrudeWallLocation.Center, 
                adsk.fusion.FeatureOperations.CutFeatureOperation
            )

        # --- EXTRUDE THE STRESS RELIEF FILLETS ---
        for profile in endFilletSketch.profiles:
             rootComp.features.extrudeFeatures.addSimple(
                 profile, 
                 adsk.core.ValueInput.createByReal(stockThickness), 
                 adsk.fusion.FeatureOperations.CutFeatureOperation
             )

    except:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))

def thinExtrude(profile, thickness, distance, side: adsk.fusion.ThinExtrudeWallLocation, operation: adsk.fusion.FeatureOperations):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface
        design = app.activeProduct
        rootComp = design.rootComponent

        # get extrude features and define the extrude input
        extrudes = rootComp.features.extrudeFeatures
        extrudeInput = extrudes.createInput(profile, operation)
        wallThickness = adsk.core.ValueInput.createByReal(thickness)
        extrudeInput.setThinExtrude(side, wallThickness)
        extrudeDistance = adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByReal(distance))
        extrudeInput.setOneSideExtent(extrudeDistance, adsk.fusion.ExtentDirections.PositiveExtentDirection)

        # create the feature
        return extrudes.add(extrudeInput)

    except:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))