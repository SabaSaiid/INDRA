'use client';

import React from 'react';
import { Search, Bell, ChevronDown, Menu } from 'lucide-react';
import { motion } from 'framer-motion';
import { fadeIn } from '@/lib/motion';

interface TopbarProps {
  onMobileMenuOpen: () => void;
}

export default function Topbar({ onMobileMenuOpen }: TopbarProps) {
  return (
    <motion.header
      variants={fadeIn}
      initial="hidden"
      animate="visible"
      className="sticky top-0 z-30 bg-white/80 backdrop-blur-xl border-b border-slate-100"
    >
      <div className="flex items-center justify-between h-16 px-4 lg:px-6">
        {/* Mobile menu button */}
        <button
          onClick={onMobileMenuOpen}
          className="md:hidden p-2 rounded-lg hover:bg-slate-100 transition-colors"
          aria-label="Open menu"
        >
          <Menu className="w-5 h-5 text-slate-600" />
        </button>

        {/* Search */}
        <div className="flex-1 max-w-xl mx-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="Search location, event or report..."
              className="w-full h-10 pl-10 pr-4 rounded-xl bg-slate-50 border border-slate-200 text-sm text-text-primary placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
              aria-label="Search"
            />
          </div>
        </div>

        {/* Right section */}
        <div className="flex items-center gap-3">
          {/* Notifications */}
          <button
            className="relative p-2 rounded-xl hover:bg-slate-50 transition-colors"
            aria-label="Notifications"
          >
            <Bell className="w-5 h-5 text-slate-500" />
            {/* Red dot badge */}
            <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-critical" />
          </button>

          {/* User */}
          <button className="flex items-center gap-2.5 pl-3 pr-2 py-1.5 rounded-xl hover:bg-slate-50 transition-colors">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-blue-700 flex items-center justify-center">
              <span className="text-white text-xs font-bold">SS</span>
            </div>
            <div className="hidden sm:block text-left">
              <p className="text-sm font-medium text-text-primary leading-tight">Sixth Sense</p>
              <p className="text-[10px] text-text-muted leading-tight">Team</p>
            </div>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 hidden sm:block" />
          </button>
        </div>
      </div>
    </motion.header>
  );
}
