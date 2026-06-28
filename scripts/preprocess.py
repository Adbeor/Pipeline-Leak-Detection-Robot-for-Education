import FreeCAD, Part
import os, glob, zipfile
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

def preprocess_file(fcstd_path):
    print(f"Preprocessing {fcstd_path}...")
    visible_names = get_visible_object_names(fcstd_path)
    
    doc = FreeCAD.openDocument(fcstd_path)
    
    visible_features = []
    for obj in doc.Objects:
        if obj.isDerivedFrom("Part::Feature") and not obj.Shape.isNull():
            # Check visibility from the GuiDocument.xml mapping
            if visible_names is None or obj.Name in visible_names:
                # Exclude default helper elements like Origin, Axes, Planes if they are not user-created features
                if obj.Name in ["Origin", "X_Axis", "Y_Axis", "Z_Axis", "XY_Plane", "XZ_Plane", "YZ_Plane"]:
                    continue
                visible_features.append(obj)
    
    if not visible_features:
        print(f"  No visible features found in {doc.Name}")
        FreeCAD.closeDocument(doc.Name)
        return
        
    print(f"  Found {len(visible_features)} visible features to export: {[o.Name for o in visible_features]}")
    
    # Create a compound of all visible shapes
    shapes = [obj.Shape for obj in visible_features]
    compound_shape = Part.makeCompound(shapes)
    
    # Create a new single feature containing the compound
    export_obj = doc.addObject("Part::Feature", "CombinedGalleryModel")
    export_obj.Shape = compound_shape
    
    # Delete all other objects from the document so export.py only sees the combined object
    for obj in list(doc.Objects):
        if obj.Name != export_obj.Name:
            doc.removeObject(obj.Name)
            
    doc.recompute()
    doc.save()
    FreeCAD.closeDocument(doc.Name)
    print(f"  Saved preprocessed document: {fcstd_path}")

def main():
    # Source FreeCAD directory (hardcoded to match cad-gallery.yaml)
    freecad_dir = "CAD"
    pattern = os.path.join(freecad_dir, "*.FCStd")
    fcstd_files = glob.glob(pattern)
    
    for f in fcstd_files:
        try:
            preprocess_file(f)
        except Exception as e:
            print(f"Error preprocessing {f}: {e}")

if __name__ == "__main__":
    main()
