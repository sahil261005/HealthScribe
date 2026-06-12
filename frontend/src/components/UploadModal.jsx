import React, { useState } from 'react';
import { aiService } from '../api';
import api from '../api';

const UploadModal = ({ isOpen, onClose, onUploadSuccess }) => {
    const [selectedFile, setSelectedFile] = useState(null);
    const [isLoading, setIsLoading] = useState(false);
    const [extractedData, setExtractedData] = useState(null);
    const [errorMessage, setErrorMessage] = useState('');

    if (!isOpen) return null;

    const handleFileSelection = (event) => {
        const file = event.target.files[0];
        setSelectedFile(file);
        setExtractedData(null);
        setErrorMessage('');
    };

    // send the file to the AI service for extraction
    const handleExtractData = async () => {
        if (!selectedFile) {
            setErrorMessage('Please select a file first.');
            return;
        }
        setIsLoading(true);
        setErrorMessage('');
        try {
            const formData = new FormData();
            formData.append('uploaded_file', selectedFile);
            const response = await aiService.post('/extract_data', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            if (response.data.error) {
                setErrorMessage('AI Error: ' + response.data.error);
                return;
            }
            setExtractedData(response.data);
        } catch {
            setErrorMessage('Failed to extract data. Is the AI service running?');
        } finally {
            setIsLoading(false);
        }
    };

    // save the verified data to django
    const handleSaveData = async () => {
        if (!extractedData) return;
        setIsLoading(true);
        try {
            const response = await api.post('save_record/', { verified_data: extractedData });
            if (response.data.warnings && response.data.warnings.length > 0) {
                alert('Record saved with warnings:\n' + response.data.warnings.join('\n'));
            }
            onUploadSuccess();
            onClose();
        } catch {
            setErrorMessage('Failed to save record.');
        } finally {
            setIsLoading(false);
        }
    };

    // handlers for editing the extracted medicines before saving
    const handleMedicineChange = (idx, field, val) => {
        const updatedMeds = [...extractedData.medicines];
        updatedMeds[idx][field] = val;
        setExtractedData({ ...extractedData, medicines: updatedMeds });
    };

    const handleRemoveMedicine = (idx) => {
        const filtered = extractedData.medicines.filter((_, i) => i !== idx);
        setExtractedData({ ...extractedData, medicines: filtered });
    };

    const handleAddMedicine = () => {
        const currentMeds = extractedData.medicines || [];
        setExtractedData({ 
            ...extractedData, 
            medicines: [...currentMeds, { name: '', dosage: '', reason: '' }] 
        });
    };

    // handlers for editing allergies
    const handleAllergyChange = (idx, val) => {
        const updatedAllergies = [...(extractedData.allergies || [])];
        updatedAllergies[idx] = val;
        setExtractedData({ ...extractedData, allergies: updatedAllergies });
    };

    const handleRemoveAllergy = (idx) => {
        const filtered = (extractedData.allergies || []).filter((_, i) => i !== idx);
        setExtractedData({ ...extractedData, allergies: filtered });
    };

    const handleAddAllergy = () => {
        const currentAllergies = extractedData.allergies || [];
        setExtractedData({ 
            ...extractedData, 
            allergies: [...currentAllergies, ''] 
        });
    };

    return (
        <div className="modal-overlay">
            <div className="modal-container">
                <div className="modal-header">
                    <div>
                        <h2 className="modal-title">Upload Medical Record</h2>
                        <p className="modal-subtitle">Upload a prescription or report to extract data</p>
                    </div>
                    <button onClick={onClose} className="btn-close">✕</button>
                </div>
                
                <div className="modal-body">
                    {/* left side - file upload */}
                    <div className="upload-column">
                        <div className={`dropzone ${selectedFile ? 'dropzone-active' : ''}`}>
                            <input
                                type="file"
                                accept="image/*,application/pdf"
                                onChange={handleFileSelection}
                                className="hidden"
                                id="file-upload"
                            />
                            <label htmlFor="file-upload" className="cursor-pointer">
                                <p className="text-sm">
                                    {selectedFile ? selectedFile.name : 'Click to upload prescription'}
                                </p>
                            </label>
                        </div>
                        
                        {selectedFile && (
                            <div className="preview-container">
                                {selectedFile.type === 'application/pdf' ? (
                                    <div className="text-center">
                                        <p className="text-sm mt-2">PDF Document Ready</p>
                                    </div>
                                ) : (
                                    <img
                                        src={URL.createObjectURL(selectedFile)}
                                        alt="Preview"
                                        className="preview-img"
                                    />
                                )}
                            </div>
                        )}
                        
                        <button
                            onClick={handleExtractData}
                            disabled={isLoading || !selectedFile}
                            className="btn-upload btn-extract-full"
                        >
                            {isLoading ? 'Processing...' : 'Extract Data'}
                        </button>

                        {errorMessage && (
                            <div className="error-alert error-alert-spaced">
                                {errorMessage}
                            </div>
                        )}
                    </div>

                    {/* right side - verify extracted data */}
                    <div className="verify-column">
                        <h3 className="section-title verify-section-title">
                            Verify Extracted Data
                        </h3>
                        
                        {extractedData ? (
                            <div>
                                {/* doctor name */}
                                <div className="input-row doctor-name-row">
                                    <span className="text-sm doctor-name-label">Doctor Name:</span>
                                    <input 
                                        className="mini-input doctor-name-input" 
                                        value={extractedData.doctor_name || ''} 
                                        onChange={(e) => setExtractedData({ 
                                            ...extractedData, 
                                            doctor_name: e.target.value 
                                        })} 
                                        placeholder="e.g. Dr. Smith (Optional)"
                                    />
                                </div>

                                {/* medicines */}
                                <div className="section-box section-blue">
                                    <div className="section-header">
                                        <h4 className="section-title">Medicines</h4>
                                        <button onClick={handleAddMedicine} className="btn-add">+ Add</button>
                                    </div>
                                    {extractedData.medicines?.map((med, i) => (
                                        <div key={i} className="input-row">
                                            <input
                                                className="mini-input"
                                                value={med.name || ''}
                                                onChange={(e) => handleMedicineChange(i, 'name', e.target.value)}
                                                placeholder="Name"
                                            />
                                            <input
                                                className="mini-input dosage-input"
                                                value={med.dosage || ''}
                                                onChange={(e) => handleMedicineChange(i, 'dosage', e.target.value)}
                                                placeholder="Dosage"
                                            />
                                            <button onClick={() => handleRemoveMedicine(i)} className="btn-close">
                                                ✕
                                            </button>
                                        </div>
                                    ))}
                                </div>

                                {/* vitals */}
                                <div className="section-box section-green">
                                    <h4 className="section-title">Vitals</h4>
                                    <div className="vitals-edit-grid">
                                        {Object.entries(extractedData.vitals || {}).map(([key, val]) => (
                                            <div key={key} className="vital-edit-item">
                                                <span className="text-sm vital-edit-label">
                                                    {key}:
                                                </span>
                                                <input 
                                                    className="mini-input" 
                                                    value={val || ''} 
                                                    onChange={(e) => setExtractedData({ 
                                                        ...extractedData, 
                                                        vitals: { ...extractedData.vitals, [key]: e.target.value } 
                                                    })} 
                                                />
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                {/* allergies */}
                                <div className="section-box section-red">
                                    <div className="section-header">
                                        <h4 className="section-title">Allergies</h4>
                                        <button onClick={handleAddAllergy} className="btn-add">+ Add</button>
                                    </div>
                                    <div className="allergies-edit-list">
                                        {extractedData.allergies?.map((allergy, i) => (
                                            <div key={i} className="input-row">
                                                <input
                                                    className="mini-input"
                                                    value={allergy || ''}
                                                    onChange={(e) => handleAllergyChange(i, e.target.value)}
                                                    placeholder="Allergy (e.g. Penicillin)"
                                                />
                                                <button onClick={() => handleRemoveAllergy(i)} className="btn-close">
                                                    ✕
                                                </button>
                                            </div>
                                        ))}
                                        {(!extractedData.allergies || extractedData.allergies.length === 0) && (
                                            <p className="text-sm text-muted">No allergies detected.</p>
                                        )}
                                    </div>
                                </div>
                            </div>
                        ) : (
                            <div className="empty-state empty-state-verify">
                                <p className="empty-text empty-text-spaced">
                                    Extract data to see results here
                                </p>
                            </div>
                        )}
                    </div>
                </div>

                <div className="modal-footer">
                    <button onClick={onClose} className="btn-cancel">Cancel</button>
                    <button
                        onClick={handleSaveData}
                        disabled={!extractedData || isLoading}
                        className="btn-save"
                    >
                        Verify & Save
                    </button>
                </div>
            </div>
        </div>
    );
};

export default UploadModal;
