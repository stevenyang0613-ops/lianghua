"""知识图谱构建模块"""
import re
import json
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
import jieba
import jieba.posseg as pseg


@dataclass
class Entity:
    """实体"""
    entity_id: str
    name: str
    entity_type: str
    properties: Dict = field(default_factory=dict)
    aliases: List[str] = field(default_factory=list)


@dataclass
class Relation:
    """关系"""
    source_id: str
    target_id: str
    relation_type: str
    properties: Dict = field(default_factory=dict)
    confidence: float = 1.0


@dataclass
class Triple:
    """三元组"""
    subject: str
    predicate: str
    object: str
    confidence: float = 1.0


class EntityExtractor:
    """实体提取器"""
    
    def __init__(self):
        # 实体类型定义
        self.entity_patterns = {
            'COMPANY': [
                r'[一-龥]{2,10}(股份|集团|公司|科技|银行|证券|保险|基金)',
                r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+(Inc|Corp|Ltd|Co))?',
            ],
            'BOND': [
                r'\d{6}[SZSH]?',
                r'[一-龥]{2,6}转债',
            ],
            'PERSON': [
                r'[一-龥]{2,4}(先生|女士|总|经理|董事长|CEO)',
            ],
            'INDICATOR': [
                r'(毛利率|净利率|ROE|ROA|PE|PB|PS|EPS)',
                r'(营业收入|净利润|现金流|资产负债率)',
            ],
            'DATE': [
                r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?',
                r'\d{4}年\d{1,2}月',
            ],
            'AMOUNT': [
                r'[\d,.]+[万亿]?元',
                r'[\d,.]+亿',
            ],
        }
        
        # 命名实体识别规则
        self.ner_rules = {
            'ORG': ['公司', '集团', '银行', '证券', '基金', '保险'],
            'LOC': ['省', '市', '区', '县', '国'],
            'TIME': ['年', '月', '日', '季度', '周'],
        }
    
    def extract(self, text: str) -> List[Entity]:
        """提取实体"""
        entities = []
        seen = set()
        
        for entity_type, patterns in self.entity_patterns.items():
            for pattern in patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    if isinstance(match, tuple):
                        match = match[0] if match else ''
                    
                    if match and match not in seen:
                        entity_id = f"{entity_type}_{len(entities)}"
                        entities.append(Entity(
                            entity_id=entity_id,
                            name=match,
                            entity_type=entity_type,
                            properties={}
                        ))
                        seen.add(match)
        
        # 使用jieba词性标注
        words = pseg.cut(text)
        for word, flag in words:
            if flag in ['nr', 'ns', 'nt', 'nz'] and word not in seen:
                entity_type = self._pos_to_entity_type(flag)
                entity_id = f"{entity_type}_{len(entities)}"
                entities.append(Entity(
                    entity_id=entity_id,
                    name=word,
                    entity_type=entity_type
                ))
                seen.add(word)
        
        return entities
    
    def _pos_to_entity_type(self, pos: str) -> str:
        """词性转实体类型"""
        mapping = {
            'nr': 'PERSON',
            'ns': 'LOCATION',
            'nt': 'ORGANIZATION',
            'nz': 'OTHER',
        }
        return mapping.get(pos, 'UNKNOWN')
    
    def extract_with_context(
        self, 
        text: str, 
        window_size: int = 50
    ) -> List[Tuple[Entity, str]]:
        """带上下文的实体提取"""
        entities = self.extract(text)
        results = []
        
        for entity in entities:
            # 找到实体位置
            idx = text.find(entity.name)
            if idx >= 0:
                start = max(0, idx - window_size)
                end = min(len(text), idx + len(entity.name) + window_size)
                context = text[start:end]
                results.append((entity, context))
        
        return results


class RelationExtractor:
    """关系提取器"""
    
    def __init__(self):
        # 关系模式
        self.relation_patterns = [
            (r'(.+?)是(.+?)的子公司', 'SUBSIDIARY'),
            (r'(.+?)持有(.+?)%股份', 'SHAREHOLDER'),
            (r'(.+?)投资(.+?)', 'INVEST'),
            (r'(.+?)发行(.+?转债)', 'ISSUE'),
            (r'(.+?)买入(.+?)', 'BUY'),
            (r'(.+?)卖出(.+?)', 'SELL'),
            (r'(.+?)合作(.+?)', 'PARTNER'),
            (r'(.+?)收购(.+?)', 'ACQUIRE'),
            (r'(.+?)对标(.+?)', 'COMPARE'),
        ]
        
        # 动词关系
        self.verb_relations = {
            '持有': 'HOLD',
            '投资': 'INVEST',
            '收购': 'ACQUIRE',
            '合作': 'PARTNER',
            '发行': 'ISSUE',
            '买入': 'BUY',
            '卖出': 'SELL',
            '增持': 'INCREASE',
            '减持': 'DECREASE',
        }
    
    def extract(self, text: str, entities: List[Entity] = None) -> List[Relation]:
        """提取关系"""
        relations = []
        entity_names = {e.name for e in entities} if entities else set()
        
        for pattern, relation_type in self.relation_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if len(match) == 2:
                    source, target = match
                    if entity_names and (source not in entity_names or target not in entity_names):
                        continue
                    
                    relations.append(Relation(
                        source_id=source,
                        target_id=target,
                        relation_type=relation_type,
                        confidence=0.8
                    ))
        
        # 基于依存句法的关系提取（简化版）
        relations.extend(self._dependency_extract(text, entities))
        
        return relations
    
    def _dependency_extract(self, text: str, entities: List[Entity]) -> List[Relation]:
        """基于依存句法的关系提取"""
        relations = []

        if not entities:
            return relations

        # 简化：查找两个实体之间的动词
        words = list(pseg.cut(text))
        entity_names = {e.name for e in entities}

        for i, pair in enumerate(words):
            word = pair.word
            flag = pair.flag
            if flag == 'v' and word in self.verb_relations:
                # 查找前后的实体
                before_entities = []
                after_entities = []

                for j in range(max(0, i-5), i):
                    if words[j].word in entity_names:
                        before_entities.append(words[j].word)

                for j in range(i+1, min(len(words), i+5)):
                    if words[j].word in entity_names:
                        after_entities.append(words[j].word)

                for source in before_entities:
                    for target in after_entities:
                        relations.append(Relation(
                            source_id=source,
                            target_id=target,
                            relation_type=self.verb_relations[word],
                            confidence=0.6
                        ))

        return relations


class KnowledgeGraph:
    """知识图谱"""
    
    def __init__(self):
        self.entities: Dict[str, Entity] = {}
        self.relations: List[Relation] = []
        self.entity_index: Dict[str, Set[str]] = defaultdict(set)  # 名称到ID索引
        self.relation_index: Dict[str, List[Relation]] = defaultdict(list)  # 关系类型索引
        
        self.entity_extractor = EntityExtractor()
        self.relation_extractor = RelationExtractor()
    
    def add_entity(self, entity: Entity):
        """添加实体"""
        self.entities[entity.entity_id] = entity
        self.entity_index[entity.name].add(entity.entity_id)
        
        for alias in entity.aliases:
            self.entity_index[alias].add(entity.entity_id)
    
    def add_relation(self, relation: Relation):
        """添加关系"""
        self.relations.append(relation)
        self.relation_index[relation.relation_type].append(relation)
    
    def build_from_text(self, text: str):
        """从文本构建知识图谱"""
        # 提取实体
        entities = self.entity_extractor.extract(text)
        for entity in entities:
            self.add_entity(entity)
        
        # 提取关系
        relations = self.relation_extractor.extract(text, entities)
        for relation in relations:
            self.add_relation(relation)
    
    def build_from_reports(self, reports: List[Dict]):
        """从研报批量构建"""
        for report in reports:
            text = report.get('content', '')
            self.build_from_text(text)
    
    def get_entity(self, name: str) -> Optional[Entity]:
        """获取实体"""
        entity_ids = self.entity_index.get(name, set())
        if entity_ids:
            return self.entities[list(entity_ids)[0]]
        return None
    
    def get_relations(
        self, 
        entity_name: str = None,
        relation_type: str = None
    ) -> List[Relation]:
        """获取关系"""
        if relation_type:
            relations = self.relation_index.get(relation_type, [])
        else:
            relations = self.relations
        
        if entity_name:
            entity_ids = self.entity_index.get(entity_name, set())
            return [r for r in relations 
                   if r.source_id in entity_ids or r.target_id in entity_ids]
        
        return relations
    
    def find_path(
        self, 
        source: str, 
        target: str, 
        max_depth: int = 3
    ) -> List[List[str]]:
        """查找路径"""
        source_ids = self.entity_index.get(source, set())
        target_ids = self.entity_index.get(target, set())
        
        if not source_ids or not target_ids:
            return []
        
        paths = []
        
        def dfs(current_id: str, path: List[str], visited: Set[str]):
            if len(path) > max_depth:
                return
            
            if current_id in target_ids:
                paths.append(path.copy())
                return
            
            if current_id in visited:
                return
            
            visited.add(current_id)
            
            # 找相邻实体
            for relation in self.relations:
                if relation.source_id == current_id:
                    path.append(f"-[{relation.relation_type}]->{relation.target_id}")
                    dfs(relation.target_id, path, visited)
                    path.pop()
                elif relation.target_id == current_id:
                    path.append(f"<-[{relation.relation_type}]-{relation.source_id}")
                    dfs(relation.source_id, path, visited)
                    path.pop()
            
            visited.remove(current_id)
        
        for source_id in source_ids:
            dfs(source_id, [source], set())
        
        return paths
    
    def get_neighbors(self, entity_name: str, depth: int = 1) -> Dict:
        """获取邻居节点"""
        entity_ids = self.entity_index.get(entity_name, set())
        
        if not entity_ids:
            return {}
        
        neighbors = defaultdict(set)
        current_level = entity_ids
        
        for _ in range(depth):
            next_level = set()
            
            for relation in self.relations:
                if relation.source_id in current_level:
                    neighbors[relation.relation_type].add(relation.target_id)
                    next_level.add(relation.target_id)
                elif relation.target_id in current_level:
                    neighbors[f"reverse_{relation.relation_type}"].add(relation.source_id)
                    next_level.add(relation.source_id)
            
            current_level = next_level
        
        # 转换为实体名称
        result = {}
        for rel_type, entity_ids in neighbors.items():
            result[rel_type] = [
                self.entities[eid].name for eid in entity_ids 
                if eid in self.entities
            ]
        
        return result
    
    def get_subgraph(
        self, 
        entity_names: List[str],
        include_relations: List[str] = None
    ) -> Dict:
        """获取子图"""
        entity_ids = set()
        for name in entity_names:
            entity_ids.update(self.entity_index.get(name, set()))
        
        # 筛选关系
        if include_relations:
            relations = [r for r in self.relations 
                        if r.relation_type in include_relations]
        else:
            relations = self.relations
        
        # 筛选相关实体
        subgraph_entities = {}
        subgraph_relations = []
        
        for relation in relations:
            if relation.source_id in entity_ids or relation.target_id in entity_ids:
                subgraph_relations.append(relation)
                
                if relation.source_id in self.entities:
                    subgraph_entities[relation.source_id] = self.entities[relation.source_id]
                if relation.target_id in self.entities:
                    subgraph_entities[relation.target_id] = self.entities[relation.target_id]
        
        return {
            'entities': {eid: {'name': e.name, 'type': e.entity_type} 
                        for eid, e in subgraph_entities.items()},
            'relations': [
                {'source': r.source_id, 'target': r.target_id, 'type': r.relation_type}
                for r in subgraph_relations
            ]
        }
    
    def export_triples(self) -> List[Triple]:
        """导出三元组"""
        triples = []
        
        for relation in self.relations:
            source_name = self.entities.get(relation.source_id, Entity('', '', '')).name
            target_name = self.entities.get(relation.target_id, Entity('', '', '')).name
            
            triples.append(Triple(
                subject=source_name,
                predicate=relation.relation_type,
                object=target_name,
                confidence=relation.confidence
            ))
        
        return triples
    
    def to_json(self) -> str:
        """导出为JSON"""
        data = {
            'entities': [
                {
                    'id': e.entity_id,
                    'name': e.name,
                    'type': e.entity_type,
                    'properties': e.properties
                }
                for e in self.entities.values()
            ],
            'relations': [
                {
                    'source': r.source_id,
                    'target': r.target_id,
                    'type': r.relation_type,
                    'confidence': r.confidence
                }
                for r in self.relations
            ]
        }
        return json.dumps(data, ensure_ascii=False, indent=2)
    
    def from_json(self, json_str: str):
        """从JSON导入"""
        data = json.loads(json_str)
        
        for entity_data in data['entities']:
            entity = Entity(
                entity_id=entity_data['id'],
                name=entity_data['name'],
                entity_type=entity_data['type'],
                properties=entity_data.get('properties', {})
            )
            self.add_entity(entity)
        
        for relation_data in data['relations']:
            relation = Relation(
                source_id=relation_data['source'],
                target_id=relation_data['target'],
                relation_type=relation_data['type'],
                confidence=relation_data.get('confidence', 1.0)
            )
            self.add_relation(relation)
    
    def query(self, query_str: str) -> List[Dict]:
        """查询知识图谱"""
        # 简单查询解析
        # 格式: "实体A 关系 实体B?" 或 "实体A 的关系?"
        
        patterns = [
            r'(.+?)的(.+?)是谁',  # 实体A的关系是谁
            r'(.+?)和(.+?)的关系',  # 实体A和实体B的关系
            r'(.+?)投资了谁',  # 特定关系查询
        ]
        
        results = []
        
        # 尝试匹配查询模式
        for pattern in patterns:
            match = re.match(pattern, query_str)
            if match:
                groups = match.groups()
                
                if len(groups) == 2:
                    entity_name, relation_hint = groups
                    
                    # 查找实体相关关系
                    relations = self.get_relations(entity_name)
                    for r in relations:
                        results.append({
                            'source': r.source_id,
                            'relation': r.relation_type,
                            'target': r.target_id,
                            'confidence': r.confidence
                        })
        
        return results
