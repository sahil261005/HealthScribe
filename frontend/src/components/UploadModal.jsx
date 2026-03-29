import React, { useState } from 'react';
import { aiService } from '../api';
import api from '../api';
import { X, Upload, Check, Pill, Stethoscope, Activity, FileText as FileTextIcon, Loader2, AlertTriangle } from 'lucide-react';

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

    // sends the file to the AI service for extraction
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
        } catch (error) {
            setErrorMessage('Failed to extract data. Is the AI service running?');
        } finally {
            setIsLoading(false);
        }
    };

    // saves the verified data to the django backend
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
        } catch (error) {
            setErrorMessage('Failed to save record.');
        } finally {
            setIsLoading(false);
        }
    };

    // handlers for editing medicines in the verification step
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
                {/* header */}
                <div className="modal-header">
                    <div>
                        <h2 className="modal-title">Upload Medical Record</h2>
                        <p className="modal-subtitle">Upload a prescription or report to extract data</p>
                    </div>
                    <button onClick={onClose} className="btn-close"><X size={22} /></button>
                </div>
                
                {/* two column layout */}
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
                                <Upload
                                    size={28}
                                    color={selectedFile ? '#27ae60' : '#999'}
                                    style={{ display: 'block', margin: '0 auto 8px' }}
                                />
                                <p className="text-sm">
                                    {selectedFile ? selectedFile.name : 'Click to upload prescription'}
                                </p>
                            </label>
                        </div>
                        
                        {selectedFile && (
                            <div className="preview-container">
                                {selectedFile.type === 'application/pdf' ? (
                                    <div className="text-center">
                                        <FileTextIcon size={40} color="#c0392b" />
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
                            className="btn-upload"
                            style={{ width: '100%', marginTop: '12px' }}
                        >
                            {isLoading ? (
                                <Loader2 size={18} style={{ animation: 'spin 1s linear infinite' }} />
                            ) : (
                                <Stethoscope size={18} />
                            )}
                            {' '}
                            {isLoading ? 'Processing...' : 'Extract Data'}
                        </button>

                        {errorMessage && (
                            <div className="error-alert" style={{ marginTop: '12px' }}>
                                {errorMessage}
                            </div>
                        )}
                    </div>

                    {/* right side - verify what the AI extracted */}
                    <div className="verify-column">
                        <h3 className="section-title" style={{ marginBottom: '14px' }}>
                            <Check size={18} color="#27ae60" /> Verify Extracted Data
                        </h3>
                        
                        {extractedData ? (
                            <div>
                                {/* medicines */}
                                <div className="section-box section-blue">
                                    <div className="section-header">
                                        <h4 className="section-title"><Pill size={14} /> Medicines</h4>
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
                                                className="mini-input"
                                                style={{ flex: '0 0 80px' }}
                                                value={med.dosage || ''}
                                                onChange={(e) => handleMedicineChange(i, 'dosage', e.target.value)}
                                                placeholder="Dosage"
                                            />
                                            <button onClick={() => handleRemoveMedicine(i)} className="btn-close">
                                                <X size={14} />
                                            </button>
                                        </div>
                                    ))}
                                </div>

                                {/* vitals */}
                                <div className="section-box section-green">
                                    <h4 className="section-title"><Activity size={14} /> Vitals</h4>
                                    <div className="input-row" style={{ flexWrap: 'wrap', gap: '10px', marginTop: '8px' }}>
                                        {Object.entries(extractedData.vitals || {}).map(([key, val]) => (
                                            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                                                <span className="text-sm" style={{ width: '60px', fontWeight: '500' }}>
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
                                        <h4 className="section-title"><AlertTriangle size={14} /> Allergies</h4>
                                        <button onClick={handleAddAllergy} className="btn-add">+ Add</button>
                                    </div>
                                    <div className="vitals-row" style={{ marginTop: '8px', flexDirection: 'column' }}>
                                        {extractedData.allergies?.map((allergy, i) => (
                                            <div key={i} className="input-row">
                                                <input
                                                    className="mini-input"
                                                    value={allergy || ''}
                                                    onChange={(e) => handleAllergyChange(i, e.target.value)}
                                                    placeholder="Allergy (e.g. Penicillin)"
                                                />
                                                <button onClick={() => handleRemoveAllergy(i)} className="btn-close">
                                                    <X size={14} />
                                                </button>
                                            </div>
                                        ))}
                                        {(!extractedData.allergies || extractedData.allergies.length === 0) && (
                                            <p className="text-sm" style={{ color: '#999' }}>No allergies detected.</p>
                                        )}
                                    </div>
                                </div>
                            </div>
                        ) : (
                            <div className="empty-state" style={{ height: '280px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                                <Stethoscope size={40} color="#ccc" />
                                <p className="empty-text" style={{ marginTop: '12px' }}>
                                    Extract data to see results here
                                </p>
                            </div>
                        )}
                    </div>
                </div>

                {/* footer buttons */}
                <div className="modal-footer">
                    <button onClick={onClose} className="btn-cancel">Cancel</button>
                    <button
                        onClick={handleSaveData}
                        disabled={!extractedData || isLoading}
                        className="btn-save"
                    >
                        <Check size={16} />
                        Verify & Save
                    </button>
                </div>
            </div>
        </div>
    );
};

export default UploadModal;
