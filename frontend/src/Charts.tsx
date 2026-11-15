import {useEffect, useRef} from 'react';
import * as echarts from './charts';
import {Activity} from 'lucide-react';
import type {Row} from './lib/types';
import {finite, formatNumber, text} from './lib/format';
import {Empty} from './ui';

export function TimeChart({rows, dark}: {rows: Row[]; dark: boolean}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current || !rows.length) return;
    const chart = echarts.init(element.current);
    const labels = rows.map(row => {
      const hour = finite(row.hour);
      const date = hour !== null ? new Date(hour * 1000) : new Date(String(row.timestamp));
      return Number.isNaN(date.getTime()) ? text(row.hour || row.timestamp) : date.toLocaleString('es-ES', {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'});
    });
    chart.setOption({
      backgroundColor: 'transparent', color: ['#c8ed78', '#ec9297'],
      grid: {top: 24, right: 22, bottom: 36, left: 47},
      tooltip: {trigger: 'axis', renderMode: 'richText', backgroundColor: dark ? '#222a24' : '#fffef9', borderColor: dark ? '#364337' : '#d8decd', textStyle: {color: dark ? '#f2f1e9' : '#1b251b'}},
      xAxis: {type: 'category', boundaryGap: false, data: labels, axisLine: {show: false}, axisTick: {show: false}, axisLabel: {color: '#8e9b8e', fontSize: 10, hideOverlap: true}},
      yAxis: {type: 'value', minInterval: 1, axisLabel: {color: '#8e9b8e', fontSize: 10}, splitLine: {lineStyle: {color: dark ? '#303b30' : '#e4e8dc', type: 'dashed'}}},
      series: [
        {name: 'Eventos recibidos', type: 'line', smooth: false, symbol: rows.length === 1 ? 'circle' : 'none', symbolSize: 7, lineStyle: {width: 2.5}, areaStyle: {color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{offset: 0, color: '#c8ed7838'}, {offset: 1, color: '#c8ed7800'}])}, data: rows.map(row => finite(row.events))},
        {name: 'Errores reportados', type: 'line', symbol: rows.length === 1 ? 'circle' : 'none', lineStyle: {width: 2}, data: rows.map(row => finite(row.errors))},
      ],
    });
    const resize = new ResizeObserver(() => chart.resize()); resize.observe(element.current);
    return () => { resize.disconnect(); chart.dispose(); };
  }, [rows, dark]);
  return rows.length ? <div className="time-chart" ref={element} role="img" aria-label="Evolución de eventos recibidos y errores reportados, por hora"/> : <Empty icon={Activity} title="Todavía no hay actividad en este período">Los eventos aparecerán cuando se confirme su llegada a RawTree.</Empty>;
}

export function BarChart({rows, labelKey, valueKey = 'rows', dark, percent = false}: {rows: Row[]; labelKey: string; valueKey?: string; dark: boolean; percent?: boolean}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current || !rows.length) return;
    const chart = echarts.init(element.current);
    chart.setOption({
      color: ['#c8ed78'], grid: {left: 54, right: 22, top: 18, bottom: 64},
      tooltip: {trigger: 'axis', renderMode: 'richText', backgroundColor: dark ? '#222a24' : '#fffef9', textStyle: {color: dark ? '#f2f1e9' : '#1b251b'}},
      xAxis: {type: 'category', data: rows.map(row => text(row[labelKey])), axisLabel: {color: '#8e9b8e', fontSize: 10, width: 100, overflow: 'truncate', rotate: rows.length > 5 ? 20 : 0}, axisTick: {show: false}, axisLine: {show: false}},
      yAxis: {type: 'value', max: percent ? 1 : undefined, axisLabel: {color: '#8e9b8e', fontSize: 10, formatter: (value: number) => percent ? `${formatNumber(value * 100)} %` : formatNumber(value)}, splitLine: {lineStyle: {color: dark ? '#303b30' : '#e4e8dc', type: 'dashed'}}},
      series: [{name: percent ? 'Exactitud' : 'Registros', type: 'bar', barMaxWidth: 45, data: rows.map(row => finite(row[valueKey])), itemStyle: {borderRadius: [5, 5, 0, 0]}}],
    });
    const resize = new ResizeObserver(() => chart.resize()); resize.observe(element.current);
    return () => { resize.disconnect(); chart.dispose(); };
  }, [rows, labelKey, valueKey, dark, percent]);
  return <div className="bar-chart" ref={element} role="img" aria-label={percent ? 'Exactitud observada por ejecución' : `Registros agrupados por ${labelKey}`}/>;
}
