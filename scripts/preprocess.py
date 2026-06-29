print("=== Starting FreeCAD Preprocessing Script ===")
import FreeCAD, Part
import os, glob, zipfile, shutil
import xml.etree.ElementTree as ET

def get_visible_object_names(fcstd_path):
    visible_names = set()
    try:
        with zipfile.ZipFile(fcstd_path) as z:
            if 'GuiDocument.xml' in z.namelist():
                xml_data = z.read('GuiDocument.xml')
                root = ET.fromstring(xml_data)
                for vp in root.findall('.//ViewProvider'):
                    name = vp.attrib.get('name')
                    vis_elem = vp.find('.//Property[@name="Visibility"]/Bool')
                    if vis_elem is not None and vis_elem.attrib.get('value') == 'true':
                        visible_names.add(name)
                    elif vis_elem is None:
                        # Default to visible if property not defined
                        visible_names.add(name)
            else:
                return None
    except Exception as e:
        print(f"Error reading zip/xml for {fcstd_path}: {e}")
        return None
    return visible_names

def is_top_level_feature(obj):
    if not obj.isDerivedFrom("Part::Feature") or obj.Shape.isNull():
        return False
    if obj.isDerivedFrom("Sketcher::SketchObject"):
        return False
    if obj.isDerivedFrom("PartDesign::FeatureDatum") or "Datum" in obj.TypeId:
        return False
    if obj.Name in ["Origin", "X_Axis", "Y_Axis", "Z_Axis", "XY_Plane", "XZ_Plane", "YZ_Plane"]:
        return False
        
    for dep in obj.InList:
        if dep.isDerivedFrom("Part::Feature"):
            # Groups or Parts do not count as parent features consuming this shape
            if dep.isDerivedFrom("App::DocumentObjectGroup") or dep.TypeId == "App::Part":
                continue
            return False
    return True

def preprocess_file(fcstd_path):
    print(f"Preprocessing {fcstd_path}...")
    visible_names = get_visible_object_names(fcstd_path)
    
    # Open document to inspect features
    doc = FreeCAD.openDocument(fcstd_path)
    
    visible_features = []
    for obj in doc.Objects:
        if is_top_level_feature(obj):
            # Check visibility from the GuiDocument.xml mapping
            if visible_names is None or obj.Name in visible_names:
                visible_features.append(obj)
    
    if not visible_features:
        print(f"  No visible features found in {doc.Name}")
        FreeCAD.closeDocument(doc.Name)
        return
        
    print(f"  Found {len(visible_features)} visible features: {[o.Name for o in visible_features]}")
    
    # Case A: Only one visible feature. No splitting needed.
    if len(visible_features) == 1:
        export_obj = doc.addObject("Part::Feature", "CombinedGalleryModel")
        export_obj.Shape = visible_features[0].Shape
        names_to_delete = [obj.Name for obj in doc.Objects if obj.Name != export_obj.Name]
        for name in names_to_delete:
            if doc.getObject(name) is not None:
                doc.removeObject(name)
        doc.recompute()
        doc.save()
        FreeCAD.closeDocument(doc.Name)
        print(f"  Saved single-body document: {fcstd_path}")
        return

    # Case B: Multiple visible features. Split them!
    feature_names = [feat.Name for feat in visible_features]
    
    # First, close the document to release file handles before copying
    doc_name = doc.Name
    FreeCAD.closeDocument(doc_name)
    
    base_dir = os.path.dirname(fcstd_path)
    base_name = os.path.splitext(os.path.basename(fcstd_path))[0]
    
    # 1. Create separate .FCStd files for each individual visible body
    for feat_name in feature_names:
        part_filename = f"{base_name}_{feat_name}.FCStd"
        part_path = os.path.join(base_dir, part_filename)
        
        # Copy the original file
        shutil.copy2(fcstd_path, part_path)
        
        # Open the copy
        part_doc = FreeCAD.openDocument(part_path)
        
        # Extract the target shape and isolate it
        target_obj = part_doc.getObject(feat_name)
        if target_obj:
            export_obj = part_doc.addObject("Part::Feature", "CombinedGalleryModel")
            export_obj.Shape = target_obj.Shape
            
            # Delete everything else so the action exporter only sees this single solid
            names_to_delete = [obj.Name for obj in part_doc.Objects if obj.Name != export_obj.Name]
            for name in names_to_delete:
                if part_doc.getObject(name) is not None:
                    try:
                        part_doc.removeObject(name)
                    except Exception as e:
                        pass
                    
        part_doc.recompute()
        part_doc.save()
        FreeCAD.closeDocument(part_doc.Name)
        print(f"  Created individual part file: {part_path}")
        
    # 2. Process the original file to act as the main combined Assembly
    assembly_doc = FreeCAD.openDocument(fcstd_path)
    assembly_features = []
    for name in feature_names:
        obj = assembly_doc.getObject(name)
        if obj:
            assembly_features.append(obj)
            
    # Combine all visible bodies into a single compound
    shapes = [obj.Shape for obj in assembly_features]
    compound_shape = Part.makeCompound(shapes)
    
    export_obj = assembly_doc.addObject("Part::Feature", "CombinedGalleryModel")
    export_obj.Shape = compound_shape
    
    # Delete all other objects so the gallery action only exports this assembly
    names_to_delete = [obj.Name for obj in assembly_doc.Objects if obj.Name != export_obj.Name]
    for name in names_to_delete:
        if assembly_doc.getObject(name) is not None:
            assembly_doc.removeObject(name)
            
    assembly_doc.recompute()
    assembly_doc.save()
    FreeCAD.closeDocument(assembly_doc.Name)
    print(f"  Saved combined assembly document: {fcstd_path}")

def main():
    # Source FreeCAD directory (hardcoded to match cad-gallery.yaml)
    freecad_dir = "CAD"
    pattern = os.path.join(freecad_dir, "*.FCStd")
    fcstd_files = glob.glob(pattern)
    
    # We must copy the list of files because we will be dynamically adding new files to this folder
    # and we do not want to recursively process the split files we create!
    files_to_process = list(fcstd_files)
    
    for f in files_to_process:
        # Ignore already-split files if we are running this multiple times locally
        basename = os.path.basename(f)
        if "_" in basename and any(basename.endswith(f"_{suffix}.FCStd") for suffix in ["Base", "Body", "Part"]):
             continue
        
        try:
            preprocess_file(f)
        except Exception as e:
            print(f"Error preprocessing {f}: {e}")

main()
