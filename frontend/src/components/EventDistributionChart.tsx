'use client';

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { fadeSlideUp } from '@/lib/motion';
import { Card, CardHeader } from '@/components/ui/card';
import { eventDistribution } from '@/lib/mock-data';
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
} from 'recharts';

const total = eventDistribution.reduce((sum, item) => sum + item.value, 0);

// Custom animated active shape for the donut
interface ActiveShapeProps {
  cx: number;
  cy: number;
  innerRadius: number;
  outerRadius: number;
  startAngle: number;
  endAngle: number;
  fill: string;
}

function AnimatedCell({ cx, cy, innerRadius, outerRadius, startAngle, endAngle, fill }: ActiveShapeProps) {
  return (
    <g>
      <path
        d={describeArc(cx, cy, outerRadius, innerRadius, startAngle, endAngle)}
        fill={fill}
        stroke="white"
        strokeWidth={2}
      />
    </g>
  );
}

function describeArc(
  cx: number,
  cy: number,
  outerRadius: number,
  innerRadius: number,
  startAngle: number,
  endAngle: number
): string {
  const RADIAN = Math.PI / 180;
  const cos1 = Math.cos(-RADIAN * startAngle);
  const sin1 = Math.sin(-RADIAN * startAngle);
  const cos2 = Math.cos(-RADIAN * endAngle);
  const sin2 = Math.sin(-RADIAN * endAngle);

  const largeArcFlag = endAngle - startAngle > 180 ? 1 : 0;

  const outerX1 = cx + outerRadius * cos1;
  const outerY1 = cy + outerRadius * sin1;
  const outerX2 = cx + outerRadius * cos2;
  const outerY2 = cy + outerRadius * sin2;
  const innerX1 = cx + innerRadius * cos1;
  const innerY1 = cy + innerRadius * sin1;
  const innerX2 = cx + innerRadius * cos2;
  const innerY2 = cy + innerRadius * sin2;

  return [
    `M ${outerX1} ${outerY1}`,
    `A ${outerRadius} ${outerRadius} 0 ${largeArcFlag} 0 ${outerX2} ${outerY2}`,
    `L ${innerX2} ${innerY2}`,
    `A ${innerRadius} ${innerRadius} 0 ${largeArcFlag} 1 ${innerX1} ${innerY1}`,
    'Z',
  ].join(' ');
}

export default function EventDistributionChart() {
  const [animate, setAnimate] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setAnimate(true), 300);
    return () => clearTimeout(timer);
  }, []);

  return (
    <motion.div
      variants={fadeSlideUp}
      initial="hidden"
      animate="visible"
      transition={{ delay: 0.5 }}
    >
      <Card hover={false} className="h-full">
        <CardHeader title="Event Distribution" />

        <div className="flex items-center gap-4">
          {/* Donut chart */}
          <div className="relative w-[160px] h-[160px] flex-shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={eventDistribution}
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={72}
                  paddingAngle={2}
                  dataKey="value"
                  startAngle={90}
                  endAngle={animate ? -270 : 90}
                  animationBegin={0}
                  animationDuration={1200}
                  animationEasing="ease-out"
                  stroke="white"
                  strokeWidth={2}
                >
                  {eventDistribution.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>

            {/* Center total */}
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <motion.span
                initial={{ opacity: 0, scale: 0.5 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 0.8, duration: 0.4, ease: 'easeOut' }}
                className="text-2xl font-bold text-text-primary tabular-nums"
              >
                {total}
              </motion.span>
              <span className="text-[10px] text-text-muted">Events</span>
            </div>
          </div>

          {/* Legend */}
          <div className="flex-1 space-y-2">
            {eventDistribution.map((item, index) => (
              <motion.div
                key={item.name}
                initial={{ opacity: 0, x: 10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.5 + index * 0.06, duration: 0.3 }}
                className="flex items-center justify-between"
              >
                <div className="flex items-center gap-2">
                  <div
                    className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ backgroundColor: item.color }}
                  />
                  <span className="text-xs text-text-secondary">{item.name}</span>
                </div>
                <span className="text-xs font-semibold text-text-primary tabular-nums">
                  {item.value}
                </span>
              </motion.div>
            ))}
          </div>
        </div>
      </Card>
    </motion.div>
  );
}
