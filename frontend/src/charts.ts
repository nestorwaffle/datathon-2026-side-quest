import {use} from 'echarts/core';
import {LineChart,BarChart} from 'echarts/charts';
import {GridComponent,TooltipComponent,LegendComponent} from 'echarts/components';
import {CanvasRenderer} from 'echarts/renderers';
use([LineChart,BarChart,GridComponent,TooltipComponent,LegendComponent,CanvasRenderer]);
export * from 'echarts/core';
