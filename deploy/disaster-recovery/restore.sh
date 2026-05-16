#!/bin/bash
# 灾难恢复脚本
# 用途：从备份区域恢复服务

set -e

# 配置变量
BACKUP_BUCKET="lianghua-backups"
TARGET_REGION="${1:-asia-east1}"
TIMESTAMP="${2:-latest}"
DB_INSTANCE="lianghua-db-$(echo $TARGET_REGION | tr '[:upper:]' '[:lower:]')"

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

error_exit() {
    log "ERROR: $1"
    exit 1
}

# 选择备份版本
select_backup_version() {
    if [ "$TIMESTAMP" = "latest" ]; then
        log "Finding latest backup..."
        TIMESTAMP=$(gsutil ls gs://${BACKUP_BUCKET}/${TARGET_REGION}/database/ | \
            grep -oP '\d{8}_\d{6}' | sort -r | head -1)
        log "Latest backup found: $TIMESTAMP"
    fi
}

# 恢复数据库
restore_database() {
    log "Restoring database from backup: $TIMESTAMP"

    # 下载备份
    gsutil cp \
        gs://${BACKUP_BUCKET}/${TARGET_REGION}/database/lianghua_db_${TIMESTAMP}.dump.gz \
        /tmp/

    # 解压
    gunzip /tmp/lianghua_db_${TIMESTAMP}.dump.gz

    # 恢复到目标数据库
    pg_restore -h $TARGET_DB_HOST -U $TARGET_DB_USER -d $TARGET_DB_NAME -c \
        /tmp/lianghua_db_${TIMESTAMP}.dump

    log "Database restoration completed"
}

# 恢复Redis
restore_redis() {
    log "Restoring Redis from backup..."

    # 下载RDB文件
    gsutil cp \
        gs://${BACKUP_BUCKET}/${TARGET_REGION}/redis/dump_${TIMESTAMP}.rdb \
        /tmp/dump.rdb

    # 停止Redis
    kubectl exec -n lianghua deployment/redis -- redis-cli SHUTDOWN NOSAVE || true
    sleep 5

    # 复制RDB文件到Redis数据目录
    kubectl cp /tmp/dump.rdb lianghua/redis-0:/data/dump.rdb

    # 重启Redis
    kubectl rollout restart deployment/redis -n lianghua

    log "Redis restoration completed"
}

# 恢复Kubernetes配置
restore_kubernetes_configs() {
    log "Restoring Kubernetes configurations..."

    # 下载配置备份
    gsutil cp \
        gs://${BACKUP_BUCKET}/${TARGET_REGION}/configs/configs_${TIMESTAMP}.tar.gz \
        /tmp/

    # 解压
    tar -xzf /tmp/configs_${TIMESTAMP}.tar.gz -C /tmp/

    # 恢复secrets
    kubectl apply -f /tmp/secrets_${TIMESTAMP}.yaml

    # 恢复configmaps
    kubectl apply -f /tmp/configmaps_${TIMESTAMP}.yaml

    log "Kubernetes configurations restored"
}

# 切换DNS到新区域
switch_dns() {
    log "Switching DNS to target region: $TARGET_REGION"

    # 更新Cloud DNS记录
    gcloud dns record-sets update lianghua.example.com \
        --zone="lianghua-zone" \
        --type="A" \
        --ttl="60" \
        --rrdatas="$TARGET_REGION_IP"

    log "DNS switched to $TARGET_REGION"
}

# 健康检查
health_check() {
    log "Running health checks..."

    # 等待服务启动
    sleep 30

    # 检查后端健康
    for i in {1..10}; do
        if curl -sf http://$TARGET_REGION_IP/api/v1/health > /dev/null; then
            log "Backend health check passed"
            return 0
        fi
        log "Waiting for backend... attempt $i"
        sleep 10
    done

    error_exit "Backend health check failed after 10 attempts"
}

# 验证数据完整性
verify_data_integrity() {
    log "Verifying data integrity..."

    # 检查数据库记录数
    local count=$(psql -h $TARGET_DB_HOST -U $TARGET_DB_USER -d $TARGET_DB_NAME -t -c "SELECT COUNT(*) FROM bonds")
    log "Database contains $count bond records"

    # 检查Redis连接
    if redis-cli -h $TARGET_REDIS_HOST ping | grep -q PONG; then
        log "Redis connection verified"
    else
        error_exit "Redis connection failed"
    fi
}

# 发送通知
send_notification() {
    local status=$1
    local message=$2

    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"Lianghua DR ${status}: ${message}\"}" \
        $SLACK_WEBHOOK_URL || true
}

# 主恢复流程
main() {
    log "Starting disaster recovery to $TARGET_REGION..."

    send_notification "Started" "DR process started for region $TARGET_REGION"

    # 选择备份版本
    select_backup_version

    # 执行恢复步骤
    restore_database || error_exit "Database restoration failed"
    restore_redis || error_exit "Redis restoration failed"
    restore_kubernetes_configs || error_exit "Config restoration failed"

    # 验证
    health_check || error_exit "Health check failed"
    verify_data_integrity || error_exit "Data integrity check failed"

    # 切换流量
    switch_dns || error_exit "DNS switch failed"

    log "Disaster recovery completed successfully"
    send_notification "Completed" "DR completed for region $TARGET_REGION using backup $TIMESTAMP"
}

# 显示帮助
show_help() {
    echo "Usage: $0 <target-region> [backup-timestamp]"
    echo ""
    echo "Arguments:"
    echo "  target-region     Target region for recovery (e.g., asia-east1, us-west1)"
    echo "  backup-timestamp  Backup timestamp to restore (default: latest)"
    echo ""
    echo "Examples:"
    echo "  $0 asia-east1                    # Restore to asia-east1 using latest backup"
    echo "  $0 us-west1 20240101_120000      # Restore to us-west1 using specific backup"
}

# 检查参数
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    show_help
    exit 0
fi

if [ -z "$TARGET_REGION" ]; then
    echo "Error: Target region required"
    show_help
    exit 1
fi

# 运行主函数
main "$@"
