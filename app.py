from flask import Flask, render_template, request, jsonify, flash, redirect, url_for, Response
import requests
from flask_bootstrap import Bootstrap
import csv
from io import StringIO

app = Flask(__name__)
app.secret_key = 'your_secret_key'
Bootstrap(app)

FHIR_SERVER_URL = "https://hapifhir4ako.duckdns.org/fhir"

@app.route('/')
def index():
    return redirect(url_for('patient_list'))

@app.route('/new_patient')
def new_patient():
    # Fetch practitioners from the FHIR server
    response = requests.get(f"{FHIR_SERVER_URL}/Practitioner")
    practitioners = []
    if response.status_code == 200:
        practitioner_entries = response.json().get('entry', [])
        for entry in practitioner_entries:
            practitioner = entry['resource']
            name = practitioner.get('name', [{}])[0]
            full_name = f"{name.get('given', [''])[0]} {name.get('family', '')}"
            practitioners.append({
                'id': practitioner['id'],
                'name': full_name
            })
    return render_template('new_patient.html', practitioners=practitioners)


@app.route('/patient_list')
def patient_list():
    response = requests.get(f"{FHIR_SERVER_URL}/Patient")
    if response.status_code == 200:
        patients = response.json().get('entry', [])
        patient_data = []
        for entry in patients:
            patient_id = entry['resource']['id']
            first_name = entry['resource'].get('name', [{}])[0].get('given', [''])[0]
            last_name = entry['resource'].get('name', [{}])[0].get('family', '')
            birth_date = entry['resource'].get('birthDate', '')
            address = entry['resource'].get('address', [{}])[0].get('text', '')
            gender = entry['resource'].get('gender', '')

            # Fetch the most recent condition (assumed as Todesursache)
            condition_response = requests.get(f"{FHIR_SERVER_URL}/Condition?patient={patient_id}")
            latest_condition = None
            if condition_response.status_code == 200:
                conditions = condition_response.json().get('entry', [])
                if conditions:
                    latest_condition_entry = conditions[-1]['resource']
                    if 'code' in latest_condition_entry and 'coding' in latest_condition_entry['code']:
                        latest_condition = latest_condition_entry['code']['coding'][0].get('display', 'Unbekannt')

            patient_data.append({
                'id': patient_id,
                'first_name': first_name,
                'last_name': last_name,
                'birth_date': birth_date,
                'address': address,
                'gender': gender,
                'latest_condition': latest_condition
            })

        return render_template('patient_list.html', patients=patient_data)
    flash('Error retrieving patients', 'danger')
    return render_template('patient_list.html', patients=[])

@app.route('/patients', methods=['POST'])
def create_patient():
    data = request.form
    practitioner_id = data['practitioner']
    patient_resource = {
        "resourceType": "Patient",
        "name": [
            {
                "given": [data['first_name']],
                "family": data['last_name']
            }
        ],
        "gender": data['gender'],
        "birthDate": data['birth_date'],
        "address": [
            {
                "text": data['address']
            }
        ]
    }

    # Erstelle den Patienten im FHIR-Server
    patient_response = requests.post(f"{FHIR_SERVER_URL}/Patient", json=patient_resource)

    if patient_response.status_code == 201:
        # Patient erfolgreich erstellt
        patient_id = patient_response.json().get('id')

        # Erstelle die Procedure-Ressource für die Totenbeschau
        procedure_resource = {
            "resourceType": "Procedure",
            "status": "completed",
            "code": {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "394914008",
                        "display": "Totenbeschau"
                    }
                ],
                "text": "Totenbeschau"
            },
            "subject": {
                "reference": f"Patient/{patient_id}"
            },
            "performer": [
                {
                    "actor": {
                        "reference": f"Practitioner/{practitioner_id}",
                        "display": "Totenbeschauarzt"
                    }
                }
            ]
        }

        procedure_response = requests.post(f"{FHIR_SERVER_URL}/Procedure", json=procedure_resource)

        if procedure_response.status_code == 201:
            flash('Patient und Totenbeschau erfolgreich erstellt', 'success')
        else:
            flash('Patient erstellt, aber Fehler beim Erstellen der Totenbeschau', 'danger')
    else:
        flash('Fehler beim Erstellen des Patienten', 'danger')

    return redirect(url_for('patient_list'))


@app.route('/conditions/<patient_id>', methods=['GET'])
def get_conditions(patient_id):
    response = requests.get(f"{FHIR_SERVER_URL}/Condition?patient={patient_id}")
    if response.status_code == 200:
        conditions = response.json().get('entry', [])
        return jsonify([{
            'id': entry['resource']['id'],
            'code': entry['resource'].get('code', {}).get('text', ''),
            'clinical_status': entry['resource'].get('clinicalStatus', {}).get('text', '')
        } for entry in conditions])
    return jsonify([]), 500

@app.route('/conditions', methods=['POST'])
def create_condition():
    data = request.json
    condition_resource = {
        "resourceType": "Condition",
        "code": {
            "text": data['code']
        },
        "clinicalStatus": {
            "text": data['clinical_status']
        },
        "subject": {
            "reference": f"Patient/{data['patient_id']}"
        }
    }
    response = requests.post(f"{FHIR_SERVER_URL}/Condition", json=condition_resource)
    if response.status_code == 201:
        return jsonify({"message": "Condition created successfully"}), 201
    return jsonify({"message": "Error creating condition"}), 500

@app.route('/conditions/<condition_id>', methods=['DELETE'])
def delete_condition(condition_id):
    response = requests.delete(f"{FHIR_SERVER_URL}/Condition/{condition_id}")
    if response.status_code == 204:
        return jsonify({"message": "Condition deleted successfully"}), 204
    return jsonify({"message": "Error deleting condition"}), 500

@app.route('/todesursachen/<patient_id>', methods=['GET', 'POST'])
def manage_todesursachen(patient_id):
    # Fetch the ValueSet for Todesursachen
    valueset_response = requests.get(f"{FHIR_SERVER_URL}/ValueSet/1")
    valueset = []
    if valueset_response.status_code == 200:
        valueset = valueset_response.json().get('compose', {}).get('include', [])[0].get('concept', [])

    if request.method == 'POST':
        data = request.form
        condition_resource = {
            "resourceType": "Condition",
            "code": {
                "coding": [
                    {
                        "system": "http://hl7.org/fhir/sid/icd-10",
                        "code": data['code'],
                        "display": data['display']
                    }
                ]
            },
            "subject": {
                "reference": f"Patient/{patient_id}"
            }
        }
        response = requests.post(f"{FHIR_SERVER_URL}/Condition", json=condition_resource)
        if response.status_code == 201:
            flash('Todesursache hinzugefügt', 'success')
        else:
            flash('Fehler beim Hinzufügen der Todesursache', 'danger')
        return redirect(url_for('manage_todesursachen', patient_id=patient_id))

    response = requests.get(f"{FHIR_SERVER_URL}/Condition?patient={patient_id}")
    conditions = []
    if response.status_code == 200:
        conditions = response.json().get('entry', [])
    return render_template('todesursachen.html', patient_id=patient_id, conditions=conditions, valueset=valueset)

@app.route('/patient_list/conditions/<patient_id>', methods=['GET'])
def patient_conditions(patient_id):
    return redirect(url_for('manage_todesursachen', patient_id=patient_id))

@app.route('/statistics')
def statistics():
    # Fetch all conditions from the FHIR server
    response = requests.get(f"{FHIR_SERVER_URL}/Condition")
    if response.status_code == 200:
        conditions = response.json().get('entry', [])
        cause_counts = {}

        for entry in conditions:
            condition = entry['resource']
            if 'code' in condition and 'coding' in condition['code']:
                code = condition['code']['coding'][0]['display']
                if code in cause_counts:
                    cause_counts[code] += 1
                else:
                    cause_counts[code] = 1

        # Sort the dictionary by values (count) in descending order
        sorted_statistics = sorted(cause_counts.items(), key=lambda x: x[1], reverse=True)
        return render_template('statistics.html', statistics=sorted_statistics)

    flash('Error retrieving statistics', 'danger')
    return render_template('statistics.html', statistics=[])

@app.route('/new_practitioner')
def new_practitioner():
    return render_template('new_practitioner.html')


@app.route('/create_practitioner', methods=['POST'])
def create_practitioner():
    """
    Erstellt einen Practitioner basierend auf Benutzereingaben.
    """
    data = request.form
    practitioner_resource = {
        "resourceType": "Practitioner",
        "name": [
            {
                "family": data['last_name'],
                "given": [data['first_name']]
            }
        ],
        "gender": data['gender'],
        "active": True
    }

    response = requests.post(f"{FHIR_SERVER_URL}/Practitioner", json=practitioner_resource)
    if response.status_code == 201:
        flash('Practitioner erfolgreich erstellt', 'success')
    else:
        flash(f"Fehler beim Erstellen des Practitioners: {response.text}", 'danger')

    return redirect(url_for('new_practitioner'))

@app.route('/export_patients_csv', methods=['POST'])
def export_patients_csv():
    selected_patient_ids = request.form.getlist('selected_patients')  # IDs der ausgewählten Patienten abrufen

    if not selected_patient_ids:
        flash('Keine Patienten ausgewählt', 'warning')
        return redirect(url_for('patient_list'))

    # CSV-Datei erstellen
    csv_output = StringIO()
    csv_writer = csv.writer(csv_output, delimiter=';')
    csv_writer.writerow(['Vorname', 'Nachname', 'Todesursache'])  # Header hinzufügen

    for patient_id in selected_patient_ids:
        # Patientendetails abrufen
        patient_response = requests.get(f"{FHIR_SERVER_URL}/Patient/{patient_id}")
        if patient_response.status_code == 200:
            patient = patient_response.json()
            first_name = patient.get('name', [{}])[0].get('given', [''])[0]
            last_name = patient.get('name', [{}])[0].get('family', '')

            # Todesursache (Condition) abrufen
            condition_response = requests.get(f"{FHIR_SERVER_URL}/Condition?patient={patient_id}")
            latest_condition = 'Unbekannt'
            if condition_response.status_code == 200:
                conditions = condition_response.json().get('entry', [])
                if conditions:
                    latest_condition_entry = conditions[-1]['resource']
                    if 'code' in latest_condition_entry and 'coding' in latest_condition_entry['code']:
                        latest_condition = latest_condition_entry['code']['coding'][0].get('display', 'Unbekannt')

            # Zeile in die CSV-Datei schreiben
            csv_writer.writerow([first_name, last_name, latest_condition])

    # CSV-Antwort erstellen
    csv_output.seek(0)
    response = Response(
        csv_output.getvalue(),
        mimetype='text/csv',
        headers={"Content-Disposition": "attachment;filename=patients.csv"}
    )
    return response



if __name__ == '__main__':
    app.run(debug=False, port=5000)
