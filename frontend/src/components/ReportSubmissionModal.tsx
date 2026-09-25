'use client';

import React, { useState, useCallback, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  MapPin,
  FileText,
  Send,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Image as ImageIcon,
  Navigation,
} from 'lucide-react';
import {
  currentPersona,
  submitCitizenReport,
  submitOfficialReport,
  type ReportSubmission,
} from '@/lib/api';

interface Props {
  open: boolean;
  onClose: () => void;
  onSubmitted?: () => void;
}

export default function ReportSubmissionModal({ open, onClose, onSubmitted }: Props) {
  const [lat, setLat] = useState('');
  const [lng, setLng] = useState('');
  const [text, setText] = useState('');
  const [mediaUrl, setMediaUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);
  const [geoLoading, setGeoLoading] = useState(false);
  // Only a Commander or Admin persona may file for a trusted source; the
  // backend enforces it (POST /api/reports/official), this only hides an
  // option that would be refused.
  const [persona, setPersona] = useState('commander');
  const [asOfficial, setAsOfficial] = useState(false);
  useEffect(() => {
    if (open) setPersona(currentPersona());
  }, [open]);
  const canFileOfficial = persona === 'commander' || persona === 'admin';

  const resetForm = useCallback(() => {
    setLat('');
    setLng('');
    setText('');
    setMediaUrl('');
    setAsOfficial(false);
    setResult(null);
  }, []);

  const handleClose = useCallback(() => {
    resetForm();
    onClose();
  }, [onClose, resetForm]);

  const detectLocation = useCallback(() => {
    if (!navigator.geolocation) return;
    setGeoLoading(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLat(pos.coords.latitude.toFixed(6));
        setLng(pos.coords.longitude.toFixed(6));
        setGeoLoading(false);
      },
      () => setGeoLoading(false),
      { enableHighAccuracy: true, timeout: 8000 }
    );
  }, []);

  const handleSubmit = async () => {
    const latitude = parseFloat(lat);
    const longitude = parseFloat(lng);
    if (isNaN(latitude) || isNaN(longitude) || text.length < 10) return;

    setSubmitting(true);
    const report: ReportSubmission = { latitude, longitude, text };
    if (mediaUrl.trim()) report.media_url = mediaUrl.trim();

    const official = asOfficial && canFileOfficial;
    const res = official ? await submitOfficialReport(report, persona) : await submitCitizenReport(report);
    if (res.success) {
      setResult({
        success: true,
        message: official
          ? `Official dispatch filed as ${persona}. It is stored with your name and scored like any report.`
          : 'Report submitted successfully! Our system is processing your report through the verification pipeline.',
      });
      onSubmitted?.();
    } else {
      setResult({ success: false, message: res.error || 'Submission failed. Please try again.' });
    }
    setSubmitting(false);
  };

  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center"
        onClick={handleClose}
      >
        <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />
        <motion.div
          initial={{ scale: 0.95, opacity: 0, y: 20 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.95, opacity: 0, y: 20 }}
          transition={{ type: 'spring', damping: 25, stiffness: 300 }}
          className="relative w-full max-w-md bg-[#F7F3EA] rounded-2xl border border-[#E8E2D4] shadow-2xl overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="px-5 py-4 border-b border-[#E8E2D4]">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-[#B5482E] flex items-center justify-center">
                  <AlertTriangle className="w-4 h-4 text-white" />
                </div>
                <div>
                  <h2 className="text-sm font-bold text-[#3C2415]">Report Incident</h2>
                  <p className="text-[10px] text-[#8C7A6B]">Submit a citizen weather/disaster report</p>
                </div>
              </div>
              <button onClick={handleClose} className="p-1.5 rounded-lg hover:bg-[#E8E2D4] transition-colors">
                <X className="w-4 h-4 text-[#8C7A6B]" />
              </button>
            </div>
          </div>

          <div className="px-5 py-4 space-y-4">
            {/* Result */}
            {result && (
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                className={`rounded-lg px-4 py-3 text-sm flex items-start gap-2 ${result.success ? 'bg-emerald-50 text-emerald-800 border border-emerald-200' : 'bg-red-50 text-red-800 border border-red-200'}`}
              >
                {result.success ? <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0" /> : <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />}
                <span>{result.message}</span>
              </motion.div>
            )}

            {!result?.success && (
              <>
                {/* Location */}
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-[#3C2415] flex items-center gap-1.5">
                    <MapPin className="w-3 h-3" /> Location
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={lat}
                      onChange={(e) => setLat(e.target.value)}
                      placeholder="Latitude"
                      className="flex-1 px-3 py-2 rounded-lg border border-[#E8E2D4] text-xs bg-white text-[#3C2415] placeholder:text-[#B0A898] focus:outline-none focus:ring-2 focus:ring-[#B5482E]/20"
                    />
                    <input
                      type="text"
                      value={lng}
                      onChange={(e) => setLng(e.target.value)}
                      placeholder="Longitude"
                      className="flex-1 px-3 py-2 rounded-lg border border-[#E8E2D4] text-xs bg-white text-[#3C2415] placeholder:text-[#B0A898] focus:outline-none focus:ring-2 focus:ring-[#B5482E]/20"
                    />
                    <button
                      onClick={detectLocation}
                      disabled={geoLoading}
                      className="px-3 py-2 rounded-lg bg-[#3C2415] text-white text-xs hover:bg-[#5C3B27] transition-colors disabled:opacity-50 flex items-center gap-1"
                    >
                      {geoLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Navigation className="w-3 h-3" />}
                    </button>
                  </div>
                </div>

                {/* Description */}
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-[#3C2415] flex items-center gap-1.5">
                    <FileText className="w-3 h-3" /> Description
                  </label>
                  <textarea
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder="Describe the incident in detail (waterlogging, building collapse, heavy rain, etc.)… minimum 10 characters"
                    className="w-full px-3 py-2 rounded-lg border border-[#E8E2D4] text-xs bg-white text-[#3C2415] placeholder:text-[#B0A898] resize-none h-24 focus:outline-none focus:ring-2 focus:ring-[#B5482E]/20"
                  />
                  <div className="text-[10px] text-[#8C7A6B] text-right">{text.length} characters</div>
                </div>

                {/* Optional media URL */}
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-[#3C2415] flex items-center gap-1.5">
                    <ImageIcon className="w-3 h-3" /> Photo / Video URL <span className="font-normal text-[#8C7A6B]">(optional)</span>
                  </label>
                  <input
                    type="text"
                    value={mediaUrl}
                    onChange={(e) => setMediaUrl(e.target.value)}
                    placeholder="https://…"
                    className="w-full px-3 py-2 rounded-lg border border-[#E8E2D4] text-xs bg-white text-[#3C2415] placeholder:text-[#B0A898] focus:outline-none focus:ring-2 focus:ring-[#B5482E]/20"
                  />
                </div>

                {canFileOfficial && (
                  <label className="flex items-start gap-2 p-3 rounded-lg border border-[#E8E2D4] bg-white text-xs text-[#3C2415] cursor-pointer">
                    <input
                      type="checkbox"
                      checked={asOfficial}
                      onChange={(e) => setAsOfficial(e.target.checked)}
                      className="mt-0.5"
                    />
                    <span>
                      <span className="font-semibold">File as an official dispatch</span>
                      <span className="block text-[10px] text-[#8C7A6B]">
                        For a report from a control room or field team. Stored as OFFICIAL_DISPATCH
                        with your name ({persona}); it lifts the event&apos;s source reliability to 1.00.
                      </span>
                    </span>
                  </label>
                )}

                {/* Submit */}
                <button
                  onClick={handleSubmit}
                  disabled={submitting || text.length < 10 || !lat || !lng || isNaN(parseFloat(lat)) || isNaN(parseFloat(lng))}
                  className="w-full py-2.5 rounded-lg bg-[#B5482E] text-white text-xs font-semibold hover:bg-[#8C3420] transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  {submitting ? 'Submitting report…' : asOfficial && canFileOfficial ? 'File Official Dispatch' : 'Submit Report'}
                </button>
              </>
            )}

            {result?.success && (
              <button
                onClick={handleClose}
                className="w-full py-2.5 rounded-lg bg-[#3C2415] text-white text-xs font-semibold hover:bg-[#5C3B27] transition-colors"
              >
                Close
              </button>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
