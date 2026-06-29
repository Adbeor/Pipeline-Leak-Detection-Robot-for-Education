import os
import json

def postprocess_gallery_colors():
    print("=== Starting Gallery Colors Post-processing ===")
    colors_file = "CAD_backup/model_colors.json"
    gallery_dir = "gallery/view"
    
    if not os.path.exists(colors_file):
        print(f"No color mapping file found at {colors_file}. Skipping.")
        return
        
    if not os.path.isdir(gallery_dir):
        print(f"Gallery detail directory not found at {gallery_dir}. Skipping.")
        return
        
    # Load color mapping
    with open(colors_file, "r") as f:
        model_colors = json.load(f)
        
    print(f"Loaded {len(model_colors)} model colors from {colors_file}")
    
    # Process each HTML file in gallery/view/
    updated_count = 0
    for filename in os.listdir(gallery_dir):
        if not filename.endswith(".html"):
            continue
            
        model_name = os.path.splitext(filename)[0]
        if model_name not in model_colors:
            continue
            
        color_hex = model_colors[model_name]
        # In Javascript, hex colors can be written as 0xRRGGBB.
        # Ensure it has the correct prefix
        if not color_hex.startswith("0x"):
            color_hex = "0x" + color_hex.replace("#", "")
            
        html_path = os.path.join(gallery_dir, filename)
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            # Replace the hardcoded material color
            target_str = "color: 0xe94560"
            replacement_str = f"color: {color_hex}"
            
            if target_str in content:
                content = content.replace(target_str, replacement_str)
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"  Updated color for {model_name} in {filename} to {color_hex}")
                updated_count += 1
            else:
                # Check if it was already updated or not found
                if replacement_str in content:
                    print(f"  {filename} is already up to date with color {color_hex}")
                else:
                    print(f"  Warning: Target material color string not found in {filename}")
        except Exception as e:
            print(f"  Error processing {filename}: {e}")
            
    print(f"Post-processing complete. Updated {updated_count} HTML files.")

if __name__ == "__main__":
    postprocess_gallery_colors()
