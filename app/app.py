from flask import Flask, render_template, request, redirect, url_for, session, flash
import requests
import csv
import os
from datetime import datetime
import subprocess
from googletrans import Translator
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from lxml import etree

import json  # เพิ่มสำหรับการจัดการ JSON

app = Flask(__name__)

# Global variables
ckan_url = ""
api_key = ""
dataset_id = ""
api_url = ""
resource_name = ""
csv_file_directory = ""
script_file_directory = ""
records = []  # To store records globally
language = 'en'  # Default language
scheduled_scripts = []  # To store scheduled scripts information
resource_ids = {}  # Dictionary to store resource IDs by resource name
scheduler = BackgroundScheduler()  # Initialize the scheduler
log_file_path = '/home/veerachart/ckan-docker/log/scheduled_scripts_log.json'  # Path to log file
log_file_path_delete = '/home/veerachart/ckan-docker/log/log_delete.txt'
translation_log_path = '/home/veerachart/ckan-docker/log/translation_log.txt'


def save_log():
    """Save scheduled scripts information to a log file."""
    with open(log_file_path, 'w') as log_file:
        json.dump(scheduled_scripts, log_file)

def load_log():
    """Load scheduled scripts information from a log file."""
    global scheduled_scripts
    if os.path.exists(log_file_path):
        with open(log_file_path, 'r') as log_file:
            scheduled_scripts = json.load(log_file)

def check_api_status(api_url):
    """Function to check the API status."""
    try:
        response = requests.get(api_url)
        if response.status_code == 200:
            return 'Available'
        else:
            return f"Error: {response.status_code}"
    except requests.exceptions.RequestException as e:
        return f"Error: {str(e)}"


def get_script_names(directory):
    """Get a list of script names in the specified directory."""
    if directory:  # Check if the directory is not empty
        return [f for f in os.listdir(directory) if f.endswith('_script.py')]
    return []  # Return empty list if directory is not set


@app.route('/')
def index():
    script_names = get_script_names(script_file_directory)  # Get script names
    api_status = check_api_status(api_url) 
    return render_template('index.html', scheduled_scripts=scheduled_scripts, script_names=script_names, api_status=api_status)  # Pass script names to template


@app.route('/remove_script/<script_name>', methods=['POST'])
def remove_script_route(script_name):
    """Route to remove a scheduled script."""
    remove_script(script_name)
    save_log()  # Save log after removing a script
    return redirect('/')  # กลับไปที่หน้าแรกหลังจากลบสคริปต์


def remove_script(script_name):
    """Remove a scheduled script by its name."""
    global scheduled_scripts
    scheduled_scripts = [script for script in scheduled_scripts if script['name'] != script_name]
    
    # ลบงานจาก scheduler
    for job in scheduler.get_jobs():
        if job.args and job.args[0] == script_name:
            scheduler.remove_job(job.id)
            break


@app.route('/config_ckan', methods=['POST', 'GET'])
def config_ckan():
    
    if request.method == 'POST':

        return render_template('config_ckan.html')  # Render the new HTML page
    return redirect(url_for('index'))  # Handle GET requests

@app.route('/show_data', methods=['POST'])
def show_data():
    global api_url, records, result_key, records_key, language, resource_name
   
    resource_name = request.form['resource_name']
    api_url = request.form['api_url']
    result_key = request.form.get('result_key')  
    records_key = request.form.get('records_key')  
    
    try:
        response = requests.get(api_url)
        response.raise_for_status()  # ตรวจสอบให้แน่ใจว่าไม่มีข้อผิดพลาดในการดึงข้อมูล
        data = response.json()  # แปลงข้อมูล JSON เป็น Python dict
        
       # ตรวจสอบว่าโครงสร้างข้อมูลเป็นไปตามที่กำหนดหรือไม่
        if result_key and records_key:  # ตรวจสอบว่ามีการกรอกคีย์ทั้งคู่
            if result_key in data and records_key in data[result_key]:
                records = data[result_key][records_key]  # ใช้โครงสร้างที่ผู้ใช้กำหนด
            else:
                flash("กรอกข้อมูลผิดพลาด กรุณาตรวจสอบ Result Key และ Records Key", "error")
                return redirect(url_for('index'))  # กลับไปยังหน้า index
        else:
            # ถ้าไม่ได้กรอกคีย์หรือกรอกคีย์เป็นค่าว่าง ให้ใช้ข้อมูลทั้งหมด
            records = data

    except requests.exceptions.RequestException as e:
        records = []  # หากเกิดข้อผิดพลาดในการดึงข้อมูล ให้ตั้ง records เป็นว่าง
        print(f"Error fetching data: {e}")
        flash("ไม่สามารถเชื่อมต่อกับ API ได้", "error")
        return redirect(url_for('index'))  # กลับไปยังหน้า index

    except ValueError:
        records = []  # หาก JSON ไม่ถูกต้องให้ตั้ง records เป็นว่าง
        flash("ไม่สามารถแปลงข้อมูล JSON ได้", "error")
        return redirect(url_for('index'))  # กลับไปยังหน้า index
    
    # Pass 'records' and 'language' to the template
    return render_template('show_data.html', records=records, enumerate=enumerate, language=language)




@app.route('/delete_data', methods=['POST'])
def delete_data():
    global records
    row_id = request.form.get('row_id')
    column_name = request.form.get('column_name')

    deleted_items = []

    # Delete a row by row_id
    if row_id:
        row_id = int(row_id)
        if row_id < len(records):
            deleted_items.append({"row": records[row_id]})  # Log the deleted row
            del records[row_id]

    # Delete a column by column_name
    if column_name:
        for record in records:
            if column_name in record:
                deleted_items.append({"column": column_name})  # Log the deleted column
                del record[column_name]

    # Save deleted items to log
    if deleted_items:
        log_file_path_delete = f'/home/veerachart/ckan-docker/log/{resource_name}_deleted_items_log.txt'
        with open(log_file_path_delete, mode='a') as log_file:
            log_file.write(f"\n[{datetime.now()}] Deleted items: {deleted_items}\n")

    return render_template('show_data.html', records=records, enumerate=enumerate, language=language)


@app.route('/translate_columns', methods=['POST'])
def translate_columns():
    selected_columns = request.form.getlist('columns')
    
    translator = Translator()
    
    for record in records:
        for key in selected_columns:
            if key in record and isinstance(record[key], str) and record[key] != '*****':
                translation = translator.translate(record[key], src='en', dest='th')
                record[key] = translation.text

    # Log translated columns
    log_translated_columns(selected_columns, resource_name)

    return render_template('show_data.html', records=records, enumerate=enumerate, language=language, selected_columns=selected_columns)


def log_translated_columns(columns, resource_name):
    """Log translated columns to a file."""
    translation_log_path = f'/home/veerachart/ckan-docker/log/{resource_name}_translated_columns_log.txt'
    with open(translation_log_path, 'a') as log_file:
        for column in columns:
            log_file.write(f"{column}\n")



@app.route('/save_to_ckan', methods=['POST'])
def save_to_ckan():
    global dataset_id, api_key, csv_file_directory, ckan_url, records, resource_ids

    # รับค่า CKAN input values
    
    ckan_url = request.form['ckan_url']
    dataset_id = request.form['dataset_id']
    api_key = request.form['api_key']
    
    csv_file_directory = request.form['csv_file_directory']
    script_file_directory = request.form['script_file_directory']  # Directory to save the script
    run_time = request.form['run_time']  # Get run time from form
    frequency = request.form['frequency']  # Get frequency from form

    # ตรวจสอบว่า resource_name ซ้ำไหม
    if resource_name in resource_ids:
        return "Resource name already exists. Please choose a different name."

    # Generate CSV file name and path
    csv_file_name = f"{resource_name}.csv"
    csv_file_path = os.path.join(csv_file_directory, csv_file_name)

    # Write data to CSV
    with open(csv_file_path, mode="w", newline='') as file:
        writer = csv.writer(file)
        if records:
            # Include all headers
            headers = records[0].keys()
            writer.writerow(headers)
            for item in records:
                writer.writerow(item.values())

    # Check if resource already exists (based on resource name)
    if resource_name not in resource_ids:
        # Upload CSV to CKAN (create resource)
        with open(csv_file_path, 'rb') as file:
            response = requests.post(f"{ckan_url}/api/3/action/resource_create",
                                     headers={"Authorization": api_key},
                                     data={
                                         "package_id": dataset_id,
                                         "name": resource_name,
                                         "format": "CSV",
                                         "url": "upload"
                                     },
                                     files={"upload": file})

            if response.status_code == 200:
                resource_id = response.json()['result']['id']  # เก็บ resource_id
                resource_ids[resource_name] = resource_id  # Save resource ID
            else:
                return f"Failed to upload CSV file: {response.text}"
    else:
        # Update existing resource
        resource_id = resource_ids[resource_name]  # ใช้ resource_id ที่เก็บไว้
        with open(csv_file_path, 'rb') as file:
            response = requests.post(f"{ckan_url}/api/3/action/resource_update",
                                     headers={"Authorization": api_key},
                                     data={
                                         "id": resource_id,
                                         "package_id": dataset_id,
                                         "name": resource_name,
                                         "format": "CSV",
                                         "url": "upload"
                                     },
                                     files={"upload": file})

            if response.status_code != 200:
                return f"Failed to update CSV file: {response.text}"

    # สร้าง Data Store (ลบ '_id')
    with open(csv_file_path, mode="r", newline='') as file:
        reader = csv.reader(file)
        headers = next(reader)  # Read the headers (first row)
        records = [row for row in reader]  # Read the remaining rows
    
    response = requests.post(f"{ckan_url}/api/3/action/datastore_create",
                             headers={"Authorization": api_key},
                             json={
                                 "resource_id": resource_id,
                                 "force": True,
                                 "fields": [{"id": field, "type": "text"} for field in headers if field != '_id'],
                                 "records": [{headers[i]: value for i, value in enumerate(record) if headers[i] != '_id'} for record in records]
                             })

    if response.status_code == 200:
        # สร้าง script ให้ใช้ resource_id เดิม
        script_file_path = generate_upload_script(ckan_url, api_key, dataset_id, resource_name, csv_file_directory, script_file_directory, resource_id)

        # Schedule the script using the returned script_file_path
        schedule_script(run_time, frequency, script_file_path)

        return redirect(url_for('index'))
    else:
        return f"Failed to create Data Store: {response.text}"

def generate_upload_script(ckan_url, api_key, dataset_id, resource_name, csv_file_directory, script_file_directory, resource_id):
    # Define script content
    script_content = f"""import requests
import os
import csv

ckan_url = '{ckan_url}'
api_key = '{api_key}'
dataset_id = '{dataset_id}'
csv_file_path = '{os.path.join(csv_file_directory, resource_name)}.csv'
resource_id = '{resource_id}'

def upload_to_ckan():
    # Read the CSV file to get headers and records
    with open(csv_file_path, mode="r", newline='') as file:
        reader = csv.reader(file)
        headers = next(reader)  # Read the headers (first row)
        records = [row for row in reader]  # Read the remaining rows

    # Update existing resource in CKAN
    with open(csv_file_path, 'rb') as file:
        response = requests.post(f"{{ckan_url}}/api/3/action/resource_update",
                                 headers={{"Authorization": api_key}} ,
                                 data={{"id": resource_id, "package_id": dataset_id, "name": '{resource_name}', "format": "CSV", "url": "upload"}} ,
                                 files={{"upload": file}})

    if response.status_code == 200:
        print("Resource updated with ID:", resource_id)

        # Clear existing records in the datastore
        delete_response = requests.post(f"{{ckan_url}}/api/3/action/datastore_delete",
                                         headers={{"Authorization": api_key}},
                                         json={{"resource_id": resource_id, "force": True}})  # Add force=True here

        if delete_response.status_code == 200:
            print("Old records deleted successfully!")

            # Create or Update Data Store
            response = requests.post(f"{{ckan_url}}/api/3/action/datastore_create",
                                     headers={{"Authorization": api_key}} ,
                                     json={{"resource_id": resource_id, "force": True, "fields": [{{"id": field, "type": "text"}} for field in headers if field != '_id'], "records": [{{headers[i]: value for i, value in enumerate(record) if headers[i] != '_id'}} for record in records]}})

            if response.status_code == 200:
                print("Data Store updated successfully!")
            else:
                print("Failed to update Data Store:", response.text)
        else:
            print("Failed to delete old records:", delete_response.text)
    else:
        print("Failed to upload CSV file:", response.text)

if __name__ == "__main__":
    upload_to_ckan()
"""

    # Save the script to a file
    script_file_path = os.path.join(script_file_directory, f"{resource_name}_script.py")
    with open(script_file_path, 'w') as script_file:
        script_file.write(script_content)
    
    return script_file_path

def schedule_script(run_time, frequency, script_file_path):
    """Schedules the generated script to run at a specified time with the given frequency."""
    hour, minute = map(int, run_time.split(':'))
    
    # ถ้าใช้รูปแบบ 12 ชั่วโมง ต้องตรวจสอบ AM/PM ด้วย
    if 'AM' in run_time or 'am' in run_time:
        if hour == 12:  # ถ้าเป็นเที่ยงคืน
            hour = 0  # แปลงเป็น 0
    elif 'PM' in run_time or 'pm' in run_time:
        if hour != 12:  # ถ้าไม่ใช่ 12 PM
            hour += 12  # แปลงเป็นรูปแบบ 24 ชั่วโมง

    # สร้าง CronTrigger ที่รองรับความถี่ในการรัน
    trigger = None
    if frequency == 'daily':
        trigger = CronTrigger(hour=hour, minute=minute)  # รันทุกวัน
    elif frequency == 'weekly':
        trigger = CronTrigger(day_of_week='sun', hour=hour, minute=minute)  # รันทุกสัปดาห์
    elif frequency == 'monthly':
        trigger = CronTrigger(day=1, hour=hour, minute=minute)  # รันทุกเดือน

    # ตั้งเวลาให้สคริปต์ทำงาน
    scheduler.add_job(run_script, trigger, args=[script_file_path, os.path.basename(script_file_path)])


    # เพิ่มรายละเอียดการ schedule ลงใน log
    scheduled_scripts.append({
        'name': os.path.basename(script_file_path),
        'time': run_time,
        'frequency': frequency,
        'status': 'Active',
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'last_run': 'Never',
        'api_status': 'Unknown'
    })

    save_log()  # บันทึก log
    print(scheduler.get_jobs())  # แสดง job ทั้งหมดที่ถูก schedule ไว้
    print(f"Script scheduled to run {frequency} at {run_time}")

def fetch_and_save_latest_data(api_url, resource_name, csv_file_directory):
    try:
        response = requests.get(api_url)
        response.raise_for_status()  # ตรวจสอบข้อผิดพลาดในการขอข้อมูล
        data = response.json()  # แปลง JSON เป็น dict ของ Python

        # สกัดข้อมูลจาก records โดยใช้ result_key และ records_key หรือใช้ data โดยตรงถ้ากุญแจว่าง
        if result_key and records_key:
            if result_key in data and records_key in data[result_key]:
                records = data[result_key][records_key]
            else:
                raise ValueError("โครงสร้างหรือกุญแจไม่ถูกต้อง.")
        else:
            records = data

        # กรองข้อมูลที่ถูกลบออก
        records = filter_out_deleted_rows_and_columns(records, resource_name)

        # โหลดคอลัมน์ที่แปลจากล็อก
        translated_columns = load_translated_columns_from_log(resource_name)
        
        # เริ่มต้นตัวแปลภาษา
        translator = Translator()

        # แปลข้อมูลใหม่ในคอลัมน์ที่แปลแล้ว
        for record in records:
            for column in translated_columns:
                if column in record and isinstance(record[column], str) and record[column] != '*****':
                    translation = translator.translate(record[column], src='en', dest='th')
                    record[column] = translation.text

        # สร้างชื่อและเส้นทางไฟล์ CSV
        csv_file_name = f"{resource_name}.csv"
        csv_file_path = os.path.join(csv_file_directory, csv_file_name)

        # เขียนข้อมูลลงใน CSV
        with open(csv_file_path, mode="w", newline='') as file:
            writer = csv.writer(file)
            if records:
                headers = records[0].keys()
                writer.writerow(headers)
                for item in records:
                    writer.writerow(item.values())

    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการดึงและบันทึกข้อมูล: {e}")
        return False
    return True

def load_translated_columns_from_log(resource_name):
    """โหลดคอลัมน์ที่แปลจากไฟล์ล็อกสำหรับทรัพยากรเฉพาะ."""
    translated_columns = set()  # ใช้ set เพื่อเก็บคอลัมน์ที่ไม่ซ้ำกัน
    translation_log_path = f'/home/veerachart/ckan-docker/log/{resource_name}_translated_columns_log.txt'

    if os.path.exists(translation_log_path):
        with open(translation_log_path, mode='r') as log_file:
            for line in log_file:
                translated_columns.add(line.strip())

    return translated_columns

def filter_out_deleted_rows_and_columns(records, resource_name):
    """กรองออกแถวและคอลัมน์ที่ถูกลบตามล็อกสำหรับทรัพยากรเฉพาะ."""
    deleted_rows, deleted_columns = load_deleted_items_from_log(resource_name)
    filtered_records = []

    # กรองแถวที่ถูกลบ
    for record in records:
        if record not in deleted_rows:
            filtered_records.append(record)

    # กรองคอลัมน์ที่ถูกลบ
    if deleted_columns:
        for record in filtered_records:
            for column in deleted_columns:
                if column in record:
                    del record[column]

    return filtered_records

def load_deleted_items_from_log(resource_name):
    """โหลดแถวและคอลัมน์ที่ถูกลบจากไฟล์ล็อกสำหรับทรัพยากรเฉพาะ."""
    deleted_rows = []
    deleted_columns = set()  # ใช้ set เพื่อเก็บคอลัมน์ที่ไม่ซ้ำกัน
    log_file_path_delete = f'/home/veerachart/ckan-docker/log/{resource_name}_deleted_items_log.txt'

    if os.path.exists(log_file_path_delete):
        with open(log_file_path_delete, mode='r') as log_file:
            for line in log_file:
                if "Deleted items:" in line:
                    deleted_data = eval(line.split("Deleted items: ")[1].strip())
                    for item in deleted_data:
                        if "row" in item:
                            deleted_rows.append(item["row"])
                        if "column" in item:
                            deleted_columns.add(item["column"])

    return deleted_rows, deleted_columns

def run_script(script_file_path, script_name):
    """ฟังก์ชันเพื่อเรียกใช้สคริปต์ที่กำหนดเวลาไว้."""
 
    print(f"กำลังเรียกใช้สคริปต์: {script_name}")

    # ดึงข้อมูลล่าสุดและบันทึกลงใน CSV
    if not fetch_and_save_latest_data(api_url, resource_name, csv_file_directory):
        print("ไม่สามารถดึงและบันทึกข้อมูลล่าสุดได้ ยกเลิกการดำเนินการของสคริปต์.")
        return
    
    try:
        # เรียกใช้สคริปต์
        subprocess.run(['python', script_file_path], check=True)

        # ถ้าสคริปต์ทำงานสำเร็จ
        print(f"สคริปต์ {script_name} ทำงานสำเร็จ!")

        # อัปเดต last_run และ api_status
        for script in scheduled_scripts:
            if script['name'] == script_name:
                script['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                script['api_status'] = api_url  # อัปเดตสถานะ API
                break

        # บันทึกล็อก
        save_log()

        jobs = scheduler.get_jobs()
        for job in jobs:
            print(f"รายละเอียดงาน: {job}")  # พิมพ์รายละเอียดของงานทั้งหมด
            if job.name == script_name:
                next_run = job.next_run_time
                if next_run:
                    print(f"สคริปต์ {script_name} จะทำงานอีกครั้งที่: {next_run}")
                else:
                    print(f"ไม่มีเวลาทำงานถัดไปที่กำหนดไว้สำหรับ {script_name}")
                break

    except subprocess.CalledProcessError as e:
        print(f"เกิดข้อผิดพลาดระหว่างการเรียกใช้สคริปต์: {e}")




if __name__ == "__main__":
    scheduler.start()  # Start the scheduler
    load_log()
    app.run(debug=True)  # Start the Flask app
