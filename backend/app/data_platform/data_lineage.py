"""数据血缘追踪"""
import json
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib


class NodeType(Enum):
    """节点类型"""
    SOURCE = "source"       # 数据源
    TABLE = "table"         # 表
    COLUMN = "column"       # 列
    TRANSFORM = "transform" # 转换
    REPORT = "report"       # 报告
    MODEL = "model"         # 模型
    API = "api"             # API


class EdgeType(Enum):
    """边类型"""
    DERIVED = "derived"     # 派生
    TRANSFORM = "transform" # 转换
    COPY = "copy"           # 复制
    AGGREGATE = "aggregate" # 聚合
    JOIN = "join"           # 连接


@dataclass
class LineageNode:
    """血缘节点"""
    node_id: str
    name: str
    node_type: NodeType
    description: str = ""
    properties: Dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class LineageEdge:
    """血缘边"""
    source_id: str
    target_id: str
    edge_type: EdgeType
    transformation: str = ""
    properties: Dict = field(default_factory=dict)


class DataLineageTracker:
    """数据血缘追踪器"""
    
    def __init__(self):
        self.nodes: Dict[str, LineageNode] = {}
        self.edges: List[LineageEdge] = []
        self.node_children: Dict[str, Set[str]] = {}
        self.node_parents: Dict[str, Set[str]] = {}
    
    def register_node(
        self,
        name: str,
        node_type: NodeType,
        description: str = "",
        properties: Dict = None
    ) -> str:
        """注册节点"""
        node_id = self._generate_node_id(name, node_type)
        
        node = LineageNode(
            node_id=node_id,
            name=name,
            node_type=node_type,
            description=description,
            properties=properties or {}
        )
        
        self.nodes[node_id] = node
        self.node_children[node_id] = set()
        self.node_parents[node_id] = set()
        
        return node_id
    
    def _generate_node_id(self, name: str, node_type: NodeType) -> str:
        """生成节点ID"""
        key = f"{node_type.value}:{name}"
        return hashlib.md5(key.encode()).hexdigest()[:12]
    
    def add_lineage(
        self,
        source_name: str,
        source_type: NodeType,
        target_name: str,
        target_type: NodeType,
        edge_type: EdgeType,
        transformation: str = ""
    ):
        """添加血缘关系"""
        # 注册源节点
        source_id = self._get_or_create_node(source_name, source_type)
        
        # 注册目标节点
        target_id = self._get_or_create_node(target_name, target_type)
        
        # 创建边
        edge = LineageEdge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            transformation=transformation
        )
        
        self.edges.append(edge)
        
        # 更新关系
        self.node_children[source_id].add(target_id)
        self.node_parents[target_id].add(source_id)
    
    def _get_or_create_node(self, name: str, node_type: NodeType) -> str:
        """获取或创建节点"""
        node_id = self._generate_node_id(name, node_type)
        
        if node_id not in self.nodes:
            self.register_node(name, node_type)
        
        return node_id
    
    def get_upstream_lineage(
        self,
        node_name: str,
        node_type: NodeType,
        depth: int = 10
    ) -> List[Dict]:
        """获取上游血缘"""
        node_id = self._generate_node_id(node_name, node_type)
        
        result = []
        visited = set()
        
        def traverse(current_id: str, current_depth: int):
            if current_depth >= depth or current_id in visited:
                return
            
            visited.add(current_id)
            
            parents = self.node_parents.get(current_id, set())
            
            for parent_id in parents:
                if parent_id in self.nodes:
                    parent = self.nodes[parent_id]
                    
                    # 找到连接边
                    edge = next((e for e in self.edges 
                               if e.source_id == parent_id and e.target_id == current_id), None)
                    
                    result.append({
                        'node_id': parent_id,
                        'name': parent.name,
                        'type': parent.node_type.value,
                        'depth': current_depth,
                        'edge_type': edge.edge_type.value if edge else None,
                        'transformation': edge.transformation if edge else None
                    })
                    
                    traverse(parent_id, current_depth + 1)
        
        traverse(node_id, 0)
        
        return result
    
    def get_downstream_lineage(
        self,
        node_name: str,
        node_type: NodeType,
        depth: int = 10
    ) -> List[Dict]:
        """获取下游血缘"""
        node_id = self._generate_node_id(node_name, node_type)
        
        result = []
        visited = set()
        
        def traverse(current_id: str, current_depth: int):
            if current_depth >= depth or current_id in visited:
                return
            
            visited.add(current_id)
            
            children = self.node_children.get(current_id, set())
            
            for child_id in children:
                if child_id in self.nodes:
                    child = self.nodes[child_id]
                    
                    # 找到连接边
                    edge = next((e for e in self.edges 
                               if e.source_id == current_id and e.target_id == child_id), None)
                    
                    result.append({
                        'node_id': child_id,
                        'name': child.name,
                        'type': child.node_type.value,
                        'depth': current_depth,
                        'edge_type': edge.edge_type.value if edge else None,
                        'transformation': edge.transformation if edge else None
                    })
                    
                    traverse(child_id, current_depth + 1)
        
        traverse(node_id, 0)
        
        return result
    
    def get_column_lineage(
        self,
        table_name: str,
        column_name: str
    ) -> Dict:
        """获取列级血缘"""
        column_id = self._generate_node_id(
            f"{table_name}.{column_name}",
            NodeType.COLUMN
        )
        
        upstream = self.get_upstream_lineage(
            f"{table_name}.{column_name}",
            NodeType.COLUMN
        )
        
        downstream = self.get_downstream_lineage(
            f"{table_name}.{column_name}",
            NodeType.COLUMN
        )
        
        return {
            'table': table_name,
            'column': column_name,
            'upstream': upstream,
            'downstream': downstream
        }
    
    def get_impact_analysis(
        self,
        node_name: str,
        node_type: NodeType
    ) -> Dict:
        """影响分析"""
        downstream = self.get_downstream_lineage(node_name, node_type)
        
        # 分类影响
        impact = {
            'tables': [],
            'reports': [],
            'models': [],
            'apis': []
        }
        
        for node in downstream:
            node_type_val = node['type']
            if node_type_val == 'table':
                impact['tables'].append(node)
            elif node_type_val == 'report':
                impact['reports'].append(node)
            elif node_type_val == 'model':
                impact['models'].append(node)
            elif node_type_val == 'api':
                impact['apis'].append(node)
        
        return {
            'source': {'name': node_name, 'type': node_type.value},
            'impact_summary': {
                'total_affected': len(downstream),
                'tables_affected': len(impact['tables']),
                'reports_affected': len(impact['reports']),
                'models_affected': len(impact['models']),
                'apis_affected': len(impact['apis'])
            },
            'details': impact
        }
    
    def export_lineage(self, format: str = "json") -> str:
        """导出血缘"""
        data = {
            'nodes': [
                {
                    'id': node.node_id,
                    'name': node.name,
                    'type': node.node_type.value,
                    'description': node.description,
                    'properties': node.properties
                }
                for node in self.nodes.values()
            ],
            'edges': [
                {
                    'source': edge.source_id,
                    'target': edge.target_id,
                    'type': edge.edge_type.value,
                    'transformation': edge.transformation
                }
                for edge in self.edges
            ]
        }
        
        if format == "json":
            return json.dumps(data, indent=2)
        
        elif format == "dot":
            return self._export_dot(data)
        
        return json.dumps(data)
    
    def _export_dot(self, data: Dict) -> str:
        """导出DOT格式（Graphviz）"""
        lines = ["digraph lineage {"]
        lines.append("  rankdir=LR;")
        lines.append("  node [shape=box];")
        
        # 节点
        for node in data['nodes']:
            color = {
                'source': 'lightblue',
                'table': 'lightgreen',
                'column': 'white',
                'transform': 'yellow',
                'report': 'pink',
                'model': 'orange',
                'api': 'purple'
            }.get(node['type'], 'white')
            
            lines.append(f'  "{node["id"]}" [label="{node["name"]}", style=filled, fillcolor={color}];')
        
        # 边
        for edge in data['edges']:
            label = edge.get('transformation', '')
            lines.append(f'  "{edge["source"]}" -> "{edge["target"]}" [label="{label}"];')
        
        lines.append("}")
        
        return "\n".join(lines)
    
    def import_lineage(self, data: str):
        """导入血缘"""
        parsed = json.loads(data)
        
        # 清空现有数据
        self.nodes.clear()
        self.edges.clear()
        self.node_children.clear()
        self.node_parents.clear()
        
        # 导入节点
        for node_data in parsed['nodes']:
            node = LineageNode(
                node_id=node_data['id'],
                name=node_data['name'],
                node_type=NodeType(node_data['type']),
                description=node_data.get('description', ''),
                properties=node_data.get('properties', {})
            )
            self.nodes[node.node_id] = node
            self.node_children[node.node_id] = set()
            self.node_parents[node.node_id] = set()
        
        # 导入边
        for edge_data in parsed['edges']:
            edge = LineageEdge(
                source_id=edge_data['source'],
                target_id=edge_data['target'],
                edge_type=EdgeType(edge_data['type']),
                transformation=edge_data.get('transformation', '')
            )
            self.edges.append(edge)
            
            self.node_children[edge.source_id].add(edge.target_id)
            self.node_parents[edge.target_id].add(edge.source_id)
    
    def find_path(
        self,
        source_name: str,
        source_type: NodeType,
        target_name: str,
        target_type: NodeType
    ) -> List[Dict]:
        """查找路径"""
        source_id = self._generate_node_id(source_name, source_type)
        target_id = self._generate_node_id(target_name, target_type)
        
        # BFS查找路径
        from collections import deque
        
        queue = deque([(source_id, [source_id])])
        visited = {source_id}
        
        while queue:
            current, path = queue.popleft()
            
            if current == target_id:
                return [
                    {
                        'node_id': nid,
                        'name': self.nodes[nid].name,
                        'type': self.nodes[nid].node_type.value
                    }
                    for nid in path if nid in self.nodes
                ]
            
            for child_id in self.node_children.get(current, set()):
                if child_id not in visited:
                    visited.add(child_id)
                    queue.append((child_id, path + [child_id]))
        
        return []
