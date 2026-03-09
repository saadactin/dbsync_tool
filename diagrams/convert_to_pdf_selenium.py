
import os
import time
import json
import base64
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def print_to_pdf(file_path, output_path):
    print(f"Converting {file_path} to {output_path}...")
    
    options = EdgeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    
    driver = None
    try:
        driver = webdriver.Edge(options=options)
        
        # Open the file
        driver.get(f"file:///{file_path.replace(os.sep, '/')}")
        
        # Wait for mermaid to render (if present)
        time.sleep(2)
        
        # Print to PDF using DevTools Protocol
        print_options = {
            'landscape': False,
            'displayHeaderFooter': False,
            'printBackground': True,
            'preferCSSPageSize': True,
        }
        
        result = driver.execute_cdp_cmd("Page.printToPDF", print_options)
        
        # Save the PDF
        with open(output_path, 'wb') as f:
            f.write(base64.b64decode(result['data']))
            
        print(f"Successfully created {output_path}")
        return True
        
    except Exception as e:
        print(f"Failed to convert {file_path}: {str(e)}")
        return False
    finally:
        if driver:
            driver.quit()

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    files_to_convert = [
        "project_diagrams.html",
        "business_use_case.html",
        "er_diagram.html",
        "data_dictionary.html",
        "dbsync_tool_project_scope.html"
    ]
    
    success_count = 0
    
    for filename in files_to_convert:
        input_path = os.path.join(base_dir, filename)
        if not os.path.exists(input_path):
            print(f"File not found: {input_path}")
            continue
            
        output_filename = filename.replace('.html', '.pdf')
        output_path = os.path.join(base_dir, output_filename)
        
        if print_to_pdf(input_path, output_path):
            success_count += 1
            
    print(f"\nCompleted: {success_count}/{len(files_to_convert)} files converted.")

if __name__ == "__main__":
    main()
