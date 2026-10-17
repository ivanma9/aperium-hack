import { describe, it, expect, vi, afterEach } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { AnalyticsContent } from '@/components/AnalyticsPanel';
import { fetchAnalytics, duration, type AnalyticsResult } from './analytics';

const empty: AnalyticsResult = {
  geography_id:'hormuz',port:null,window_hours:24,generated_at:1000,stream_status:'subscribed',boundary_version:'test',boundaries:[],
  classification:[],port_calls:[],waiting_times:[],transit_counts:{},
  configuration:{terminal_boundaries:0,reviewed_waiting_boundaries:0},
  congestion:{status:'boundaries_not_configured',waiting_tankers:null,observed_waits:[],by_boundary:{}},
  quality:{observed_vessels:0,tanker_vessels:0,unclassified_vessels:0,discontinuities:0,
    coverage_completeness:'unverified',observation_status:'no_observations',latest_observed_at:null,note:'Observed only'},
};
afterEach(() => vi.unstubAllGlobals());

describe('Observed analytics', () => {
  it('shows all five features with distinct unavailable states', () => {
    const content = (view: 'classification'|'calls'|'waiting'|'congestion'|'transits') =>
      renderToStaticMarkup(createElement(AnalyticsContent,{data:empty,view}));
    expect(content('classification')).toContain('No vessel observations');
    expect(content('calls')).toContain('Terminal boundaries not configured');
    expect(content('waiting')).toContain('Reviewed waiting-area boundaries are required');
    expect(content('congestion')).toContain('—');
    expect(content('transits')).toContain('No checkpoint gates');
  });
  it('renders real observations and labels candidate calls and experimental gates', () => {
    const stay={id:'v1',mmsi:'123456789',boundary_id:'terminal',port:'fujairah',kind:'terminal_call_candidate' as const,
      reviewed_boundary:false,entry_observed:false,first_seen_at:100,last_seen_at:700,observed_seconds:600,
      departure_observed_at:null,end_reason:'ongoing'};
    const data={...empty,classification:[{mmsi:'123456789',name:'SHIP',vessel_class:'tanker',ship_type:80,source:'ais_self_reported',last_seen_at:700,stale:false,classification_updated_at:500}],
      port_calls:[stay],waiting_times:[stay],configuration:{terminal_boundaries:1,reviewed_waiting_boundaries:1},
      congestion:{...empty.congestion,status:'observed_waiting_only',waiting_tankers:1,observed_waits:[stay]},
      quality:{...empty.quality,observed_vessels:1,observation_status:'recent_observations'},
      transit_counts:{gate:{reviewed_boundary:false,source:'Analyst gate',negative_to_positive:2,positive_to_negative:3}}};
    expect(renderToStaticMarkup(createElement(AnalyticsContent,{data,view:'classification'}))).toContain('SHIP');
    expect(renderToStaticMarkup(createElement(AnalyticsContent,{data,view:'calls'}))).toContain('Arrival time unknown');
    expect(renderToStaticMarkup(createElement(AnalyticsContent,{data,view:'waiting'}))).toContain('10 min');
    expect(renderToStaticMarkup(createElement(AnalyticsContent,{data,view:'congestion'}))).toContain('123456789');
    expect(renderToStaticMarkup(createElement(AnalyticsContent,{data,view:'transits'}))).toContain('Experimental');
  });
  it('requests the selected geography/port/window through the existing proxy', async () => {
    const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>empty});
    vi.stubGlobal('fetch',fetch);
    const signal=new AbortController().signal;
    await fetchAnalytics('hormuz',6,'fujairah',signal);
    expect(fetch).toHaveBeenCalledWith('/aperium/analytics?geography=hormuz&hours=6&port=fujairah',{signal,cache:'no-store'});
  });
  it('surfaces backend errors rather than returning empty counts', async () => {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:422,json:async()=>({detail:'Too many observations'})}));
    await expect(fetchAnalytics('hormuz',168,'',new AbortController().signal)).rejects.toThrow('Too many observations');
    expect(duration(null)).toBe('Unknown');
    expect(duration(3600)).toBe('1.0 h');
  });
});
