"""Tests for deployment configurations"""
import pytest
import yaml
import os
from pathlib import Path

# 部署配置目录：相对于项目根目录（backend/tests/ → backend/ → 项目根）
_DEPLOY_DIR = Path(__file__).resolve().parent.parent.parent / "deploy"
DEPLOY_ROOT = str(_DEPLOY_DIR)
requires_deploy_dir = pytest.mark.skipif(
    not os.path.exists(DEPLOY_ROOT),
    reason=f"部署配置目录不存在: {DEPLOY_ROOT} (开发环境无需此测试)",
)


@requires_deploy_dir
class TestArgoCDConfig:
    """ArgoCD配置测试"""

    def test_argocd_application_config_exists(self):
        """测试ArgoCD Application配置存在"""
        config_path = f"{DEPLOY_ROOT}/argocd/argo-cd.yaml"
        assert os.path.exists(config_path)

    def test_argocd_application_yaml_valid(self):
        """测试ArgoCD配置YAML有效性"""
        config_path = f"{DEPLOY_ROOT}/argocd/argo-cd.yaml"
        with open(config_path) as f:
            docs = list(yaml.safe_load_all(f))

        assert len(docs) > 0

        # 验证Application配置
        app = docs[0]
        assert app['kind'] == 'Application'
        assert app['metadata']['name'] == 'lianghua'

    def test_argocd_sync_policy(self):
        """测试同步策略配置"""
        config_path = f"{DEPLOY_ROOT}/argocd/argo-cd.yaml"
        with open(config_path) as f:
            docs = list(yaml.safe_load_all(f))

        app = docs[0]
        sync_policy = app['spec']['syncPolicy']

        assert sync_policy['automated']['prune'] is True
        assert sync_policy['automated']['selfHeal'] is True

    def test_argocd_application_set(self):
        """测试ApplicationSet配置"""
        config_path = f"{DEPLOY_ROOT}/argocd/argo-cd.yaml"
        with open(config_path) as f:
            docs = list(yaml.safe_load_all(f))

        # 找到ApplicationSet
        appset = None
        for doc in docs:
            if doc and doc.get('kind') == 'ApplicationSet':
                appset = doc
                break

        assert appset is not None
        assert appset['metadata']['name'] == 'lianghua-environments'


@requires_deploy_dir
class TestIstioConfig:
    """Istio配置测试"""

    def test_istio_gateway_config_exists(self):
        """测试Istio Gateway配置存在"""
        config_path = f"{DEPLOY_ROOT}/istio/gateway.yaml"
        assert os.path.exists(config_path)

    def test_istio_gateway_yaml_valid(self):
        """测试Istio Gateway配置有效性"""
        config_path = f"{DEPLOY_ROOT}/istio/gateway.yaml"
        with open(config_path) as f:
            docs = list(yaml.safe_load_all(f))

        assert len(docs) > 0

        # 验证Gateway
        gateway = docs[0]
        assert gateway['kind'] == 'Gateway'

    def test_istio_virtual_service(self):
        """测试VirtualService配置"""
        config_path = f"{DEPLOY_ROOT}/istio/gateway.yaml"
        with open(config_path) as f:
            docs = list(yaml.safe_load_all(f))

        # 找到VirtualService
        vs = None
        for doc in docs:
            if doc and doc.get('kind') == 'VirtualService':
                vs = doc
                break

        assert vs is not None
        assert 'http' in vs['spec']

    def test_istio_destination_rule(self):
        """测试DestinationRule配置"""
        config_path = f"{DEPLOY_ROOT}/istio/gateway.yaml"
        with open(config_path) as f:
            docs = list(yaml.safe_load_all(f))

        # 找到DestinationRule
        dr = None
        for doc in docs:
            if doc and doc.get('kind') == 'DestinationRule':
                dr = doc
                break

        assert dr is not None
        assert 'trafficPolicy' in dr['spec']

    def test_canary_deployment_config(self):
        """测试金丝雀发布配置"""
        config_path = f"{DEPLOY_ROOT}/istio/canary.yaml"
        assert os.path.exists(config_path)

        with open(config_path) as f:
            docs = list(yaml.safe_load_all(f))

        # 验证金丝雀路由
        canary_vs = docs[0]
        routes = canary_vs['spec']['http'][0]['route']

        # 应有两个路由（v1和v2）
        assert len(routes) == 2

        # 验证权重分配
        weights = [r['weight'] for r in routes]
        assert sum(weights) == 100


@requires_deploy_dir
class TestVaultConfig:
    """Vault配置测试"""

    def test_vault_config_exists(self):
        """测试Vault配置存在"""
        config_path = f"{DEPLOY_ROOT}/vault/vault.yaml"
        assert os.path.exists(config_path)

    def test_vault_statefulset_config(self):
        """测试Vault StatefulSet配置"""
        config_path = f"{DEPLOY_ROOT}/vault/vault.yaml"
        with open(config_path) as f:
            docs = list(yaml.safe_load_all(f))

        # 找到StatefulSet
        sts = None
        for doc in docs:
            if doc and doc.get('kind') == 'StatefulSet':
                sts = doc
                break

        assert sts is not None
        assert sts['metadata']['name'] == 'vault'
        assert sts['spec']['replicas'] >= 1

    def test_vault_policies_exist(self):
        """测试Vault策略配置存在"""
        config_path = f"{DEPLOY_ROOT}/vault/policies.yaml"
        assert os.path.exists(config_path)

    def test_k8s_auth_config(self):
        """测试Kubernetes认证配置"""
        config_path = f"{DEPLOY_ROOT}/vault/k8s-auth.yaml"
        with open(config_path) as f:
            docs = list(yaml.safe_load_all(f))

        # 验证ServiceAccount
        sa = docs[0]
        assert sa['kind'] == 'ServiceAccount'
        assert 'lianghua-backend' in sa['metadata']['name']


@requires_deploy_dir
class TestDisasterRecoveryConfig:
    """灾难恢复配置测试"""

    def test_backup_script_exists(self):
        """测试备份脚本存在"""
        script_path = f"{DEPLOY_ROOT}/disaster-recovery/backup.sh"
        assert os.path.exists(script_path)

    def test_restore_script_exists(self):
        """测试恢复脚本存在"""
        script_path = f"{DEPLOY_ROOT}/disaster-recovery/restore.sh"
        assert os.path.exists(script_path)

    def test_dr_config_yaml_valid(self):
        """测试灾难恢复配置有效性"""
        config_path = f"{DEPLOY_ROOT}/disaster-recovery/dr-config.yaml"
        with open(config_path) as f:
            docs = list(yaml.safe_load_all(f))

        assert len(docs) > 0

        # 验证ConfigMap
        cm = docs[0]
        assert cm['kind'] == 'ConfigMap'
        assert 'primary-region' in cm['data']

    def test_backup_cronjob_config(self):
        """测试备份CronJob配置"""
        config_path = f"{DEPLOY_ROOT}/disaster-recovery/dr-config.yaml"
        with open(config_path) as f:
            docs = list(yaml.safe_load_all(f))

        # 找到CronJob
        cronjob = None
        for doc in docs:
            if doc and doc.get('kind') == 'CronJob':
                cronjob = doc
                break

        assert cronjob is not None
        assert cronjob['metadata']['name'] == 'backup-job'
        assert 'schedule' in cronjob['spec']

    def test_rpo_rto_config(self):
        """测试RPO/RTO配置"""
        config_path = f"{DEPLOY_ROOT}/disaster-recovery/dr-config.yaml"
        with open(config_path) as f:
            docs = list(yaml.safe_load_all(f))

        cm = docs[0]
        data = cm['data']

        # RPO应在合理范围内
        rpo = int(data['rpo-minutes'])
        assert 0 < rpo <= 1440  # 不超过1天

        # RTO应在合理范围内
        rto = int(data['rto-minutes'])
        assert 0 < rto <= 480  # 不超过8小时


@requires_deploy_dir
class TestIntegrationConfig:
    """集成配置测试"""

    def test_all_deploy_configs_exist(self):
        """测试所有部署配置存在"""
        deploy_dir = f"{DEPLOY_ROOT}"

        required_paths = [
            "argocd/argo-cd.yaml",
            "argocd/notifications.yaml",
            "istio/gateway.yaml",
            "istio/canary.yaml",
            "vault/vault.yaml",
            "vault/policies.yaml",
            "disaster-recovery/backup.sh",
            "disaster-recovery/restore.sh",
        ]

        for path in required_paths:
            full_path = os.path.join(deploy_dir, path)
            assert os.path.exists(full_path), f"Missing: {path}"

    def test_yaml_files_syntax_valid(self):
        """测试所有YAML文件语法有效"""
        import glob

        deploy_dir = f"{DEPLOY_ROOT}"
        yaml_files = glob.glob(f"{deploy_dir}/**/*.yaml", recursive=True)

        # 需要跳过的文件列表（非YAML格式或模板文件）
        skip_patterns = [
            "templates/",           # Helm模板文件（包含Go模板语法）
            "vault/policies.yaml",  # Vault策略使用HCL格式，非YAML
        ]

        for yaml_file in yaml_files:
            # 检查是否需要跳过
            should_skip = any(pattern in yaml_file for pattern in skip_patterns)
            if should_skip:
                continue

            with open(yaml_file) as f:
                try:
                    list(yaml.safe_load_all(f))
                except yaml.YAMLError as e:
                    pytest.fail(f"Invalid YAML in {yaml_file}: {e}")
