print("=== Starting FreeCAD Preprocessing Script ===")
import FreeCAD, Part
import os, glob, zipfile, shutil, re, json
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
    is_part_feature = obj.isDerivedFrom("Part::Feature")
    is_container = obj.isDerivedFrom("App::Part") or obj.TypeId == "App::LinkGroup" or obj.isDerivedFrom("App::Link")
    
    if not (is_part_feature or is_container):
        return False
        
    if is_container:
        # A container is top-level unless it is nested inside another container
        for dep in obj.InList:
            if dep.isDerivedFrom("App::Part") or dep.TypeId == "App::LinkGroup" or dep.isDerivedFrom("App::Link") or "Link" in dep.TypeId:
                return False
        return True
        
    # For loose Part::Feature objects:
    if obj.Shape.isNull():
        return False
    if obj.isDerivedFrom("Sketcher::SketchObject"):
        return False
    if obj.isDerivedFrom("PartDesign::FeatureDatum") or "Datum" in obj.TypeId:
        return False
    if obj.Name in ["Origin", "X_Axis", "Y_Axis", "Z_Axis", "XY_Plane", "XZ_Plane", "YZ_Plane"]:
        return False
        
    for dep in obj.InList:
        # Reject if inside a container
        if dep.isDerivedFrom("App::Part") or dep.TypeId == "App::LinkGroup" or dep.isDerivedFrom("App::Link") or "Link" in dep.TypeId:
            return False
            
        # Reject if consumed by another Part::Feature (e.g. a Fusion or Cut)
        if dep.isDerivedFrom("Part::Feature"):
            if dep.isDerivedFrom("App::DocumentObjectGroup") or dep.TypeId == "App::Part":
                continue
            if dep.isDerivedFrom("PartDesign::SubShapeBinder") or "SubShapeBinder" in dep.TypeId:
                continue
            if dep.isDerivedFrom("Sketcher::SketchObject"):
                continue
            if dep.isDerivedFrom("PartDesign::FeatureDatum") or "Datum" in dep.TypeId:
                continue
            return False
            
    return True

model_colors = {}

def get_color_from_xml(root, obj_name):
    # Method 1: Check new ShapeAppearance property
    vp = root.find(f".//ViewProvider[@name='{obj_name}']")
    if vp is not None:
        sa_prop = vp.find('.//Property[@name="ShapeAppearance"]')
        if sa_prop is not None:
            ml_elem = sa_prop.find('MaterialList')
            if ml_elem is not None:
                return {"type": "ShapeAppearance", "file": ml_elem.attrib.get('file')}
                
        # Method 2: Check old ShapeColor property
        sc_prop = vp.find('.//Property[@name="ShapeColor"]')
        if sc_prop is not None:
            color_elem = sc_prop.find('Color')
            if color_elem is not None:
                try:
                    r = int(float(color_elem.attrib.get('r', '0.8')) * 255)
                    g = int(float(color_elem.attrib.get('g', '0.8')) * 255)
                    b = int(float(color_elem.attrib.get('b', '0.8')) * 255)
                    return f"0x{r:02x}{g:02x}{b:02x}"
                except Exception:
                    pass
                    
        # Method 3: Check DiffuseColor
        df_prop = vp.find('.//Property[@name="DiffuseColor"]')
        if df_prop is not None:
            color_elem = df_prop.find('.//Color')
            if color_elem is not None:
                try:
                    r = int(float(color_elem.attrib.get('r', '0.8')) * 255)
                    g = int(float(color_elem.attrib.get('g', '0.8')) * 255)
                    b = int(float(color_elem.attrib.get('b', '0.8')) * 255)
                    return f"0x{r:02x}{g:02x}{b:02x}"
                except Exception:
                    pass
    return None

def resolve_zip_color(fcstd_path, file_info):
    if not file_info:
        return None
    if isinstance(file_info, str):
        return file_info
        
    try:
        with zipfile.ZipFile(fcstd_path) as z:
            file_name = file_info.get("file")
            if file_name and file_name in z.namelist():
                content = z.read(file_name)
                if len(content) >= 12:
                    r = content[9]
                    g = content[10]
                    b = content[11]
                    return f"0x{r:02x}{g:02x}{b:02x}"
    except Exception:
        pass
    return None

def is_assembly_file(filename):
    name_lower = filename.lower()
    return "assembly" in name_lower or "ensamble" in name_lower

def preprocess_file(fcstd_path):
    basename = os.path.basename(fcstd_path)
    is_assembly = is_assembly_file(basename)
    
    print(f"Preprocessing {fcstd_path} (is_assembly={is_assembly})...")
    visible_names = get_visible_object_names(fcstd_path)
    
    # Read XML root for shape colors
    xml_root = None
    try:
        with zipfile.ZipFile(fcstd_path) as z:
            if 'GuiDocument.xml' in z.namelist():
                xml_root = ET.fromstring(z.read('GuiDocument.xml'))
    except Exception:
        pass
        
    # Open document to inspect features
    doc = FreeCAD.openDocument(fcstd_path)
    
    visible_features = []
    for obj in doc.Objects:
        # Exclude default helper elements
        if obj.Name in ["Origin", "X_Axis", "Y_Axis", "Z_Axis", "XY_Plane", "XZ_Plane", "YZ_Plane"]:
            continue
            
        if is_assembly:
            # For assembly files, gather all visible shapes (links, bodies, features)
            if hasattr(obj, "Shape") and obj.Shape is not None and not obj.Shape.isNull():
                if visible_names is None or obj.Name in visible_names:
                    # Also skip datum elements or sketches that might be visible
                    if obj.isDerivedFrom("Sketcher::SketchObject") or "Datum" in obj.TypeId:
                        continue
                    visible_features.append(obj)
        else:
            # For part files, gather only top-level bodies/solids
            if is_top_level_feature(obj):
                if visible_names is None or obj.Name in visible_names:
                    visible_features.append(obj)
    
    backup_dir = "CAD_backup"
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, basename)
    
    if not visible_features:
        print(f"  No visible features found in {doc.Name}. Moving to backup.")
        FreeCAD.closeDocument(doc.Name)
        # Move the original file out of CAD/ so it is ignored by the gallery builder
        shutil.move(fcstd_path, backup_path)
        return
        
    print(f"  Found {len(visible_features)} visible features: {[o.Name for o in visible_features]}")
    
    # Case A: Only one visible feature. Isolate it in the original file
    if len(visible_features) == 1:
        base_name = os.path.splitext(basename)[0]
        color_val = "0x807972"
        if xml_root:
            color_info = get_color_from_xml(xml_root, visible_features[0].Name)
            resolved_color = resolve_zip_color(fcstd_path, color_info)
            if resolved_color:
                color_val = resolved_color
        model_colors[base_name] = color_val
        print(f"  Model {base_name} color: {color_val}")
                
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

    # Case B: Multiple visible features.
    # Collect unique cleaned label suffixes for each feature and save color
    feature_info = []
    used_suffixes = set()
    base_name = os.path.splitext(basename)[0]
    
    for feat in visible_features:
        # Clean the label for use in the filename
        clean_label = re.sub(r'[\s\-]+', '_', feat.Label)
        clean_label = re.sub(r'[^\w]', '', clean_label)
        
        # If empty or too generic, fallback to internal Name
        if not clean_label or clean_label.lower() in ["body", "part", "solid", "group"]:
            suffix = feat.Name
        else:
            suffix = clean_label
            
        # Prevent collisions
        final_suffix = suffix
        counter = 1
        while final_suffix in used_suffixes:
            final_suffix = f"{suffix}_{counter}"
            counter += 1
            
        used_suffixes.add(final_suffix)
        feature_info.append((feat.Name, final_suffix))
        
        # Save color mapping
        color_val = "0x807972"
        if xml_root:
            color_info = get_color_from_xml(xml_root, feat.Name)
            resolved_color = resolve_zip_color(fcstd_path, color_info)
            if resolved_color:
                color_val = resolved_color
        model_colors[f"{base_name}_{final_suffix}"] = color_val
        print(f"  Model {base_name}_{final_suffix} color: {color_val}")
        
    doc_name = doc.Name
    FreeCAD.closeDocument(doc_name)
    
    base_dir = os.path.dirname(fcstd_path)
    
    if is_assembly:
        # If it is an assembly file, we only want the combined model, NO individual parts
        print(f"  Generating combined assembly model...")
        assembly_doc = FreeCAD.openDocument(fcstd_path)
        assembly_features = []
        for feat_name, _ in feature_info:
            obj = assembly_doc.getObject(feat_name)
            if obj:
                assembly_features.append(obj)
                
        # Combine all visible shapes into a single compound
        shapes = [obj.Shape for obj in assembly_features]
        compound_shape = Part.makeCompound(shapes)
        
        export_obj = assembly_doc.addObject("Part::Feature", "CombinedGalleryModel")
        export_obj.Shape = compound_shape
        
        # Clear everything else
        names_to_delete = [obj.Name for obj in assembly_doc.Objects if obj.Name != export_obj.Name]
        for name in names_to_delete:
            if assembly_doc.getObject(name) is not None:
                assembly_doc.removeObject(name)
                
        assembly_doc.recompute()
        assembly_doc.save()
        FreeCAD.closeDocument(assembly_doc.Name)
        print(f"  Saved combined assembly document: {fcstd_path}")
        
    else:
        # If it is NOT an assembly file, we only want the individual parts, NO combined model
        print(f"  Generating individual part files only...")
        # 1. Create separate .FCStd files for each individual visible body
        for feat_name, suffix in feature_info:
            part_filename = f"{base_name}_{suffix}.FCStd"
            part_path = os.path.join(base_dir, part_filename)
            
            shutil.copy2(fcstd_path, part_path)
            part_doc = FreeCAD.openDocument(part_path)
            
            target_obj = part_doc.getObject(feat_name)
            if target_obj:
                export_obj = part_doc.addObject("Part::Feature", "CombinedGalleryModel")
                export_obj.Shape = target_obj.Shape
                
                names_to_delete = [obj.Name for obj in part_doc.Objects if obj.Name != export_obj.Name]
                for name in names_to_delete:
                    if part_doc.getObject(name) is not None:
                        try:
                            part_doc.removeObject(name)
                        except Exception:
                            pass
            part_doc.recompute()
            part_doc.save()
            FreeCAD.closeDocument(part_doc.Name)
            print(f"  Created individual part file: {part_path}")
            
        # 2. Move original to backup directory so it is ignored by the gallery builder
        shutil.move(fcstd_path, backup_path)
        print(f"  Moved original file to backup: {backup_path}")

def main():
    # Source FreeCAD directory (hardcoded to match cad-gallery.yaml)
    freecad_dir = "CAD"
    pattern = os.path.join(freecad_dir, "*.FCStd")
    fcstd_files = glob.glob(pattern)
    
    files_to_process = list(fcstd_files)
    
    for f in files_to_process:
        # Ignore already-split files if we are running this multiple times locally
        basename = os.path.basename(f)
        basename_no_ext = os.path.splitext(basename)[0]
        
        # Check if this file is a split file by seeing if any base file prefix matches it
        is_split = False
        for potential_base in files_to_process:
            base_name_str = os.path.splitext(os.path.basename(potential_base))[0]
            if base_name_str != basename_no_ext and basename_no_ext.startswith(base_name_str + "_"):
                is_split = True
                break
        # Also check against already backed up base files
        if not is_split and os.path.exists("CAD_backup"):
            for backup_file in os.listdir("CAD_backup"):
                if backup_file.endswith(".FCStd"):
                    backup_no_ext = os.path.splitext(backup_file)[0]
                    if basename_no_ext.startswith(backup_no_ext + "_"):
                        is_split = True
                        break
                        
        if is_split:
            continue
        
        try:
            preprocess_file(f)
        except Exception as e:
            print(f"Error preprocessing {f}: {e}")
            
    # Save the gathered colors to a JSON file in CAD_backup
    backup_dir = "CAD_backup"
    os.makedirs(backup_dir, exist_ok=True)
    with open(os.path.join(backup_dir, "model_colors.json"), "w") as f:
        json.dump(model_colors, f, indent=4)
    print(f"Saved model colors mapping to {os.path.join(backup_dir, 'model_colors.json')}")

main()
