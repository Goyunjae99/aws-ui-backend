pipeline {
    agent any
    environment {
        DEPLOY_PATH = "/opt/h-cmp"
        WAS_SERVERS = "192.168.40.17 192.168.40.18"
    }
    
    stages {
        stage('Deploy to WAS Cluster') {
            steps {
                sshagent(['was-ssh-key']) {
                    script {
                        def servers = WAS_SERVERS.split(' ')
                        for (server in servers) {
                            echo "🚀 ${server} 서버 배포 및 스크립트 실행"
                            
                            // 1. 소스 전송 (start.sh 포함)
                            sh "rsync -avz -e 'ssh -o StrictHostKeyChecking=no' --exclude='.git' --delete ./ root@${server}:${DEPLOY_PATH}/"
                            
                            // 2. 스크립트에 실행 권한 부여 및 실행
                            sh """
                                ssh -o StrictHostKeyChecking=no root@${server} "
                                    chmod +x ${DEPLOY_PATH}/start.sh;
                                    ${DEPLOY_PATH}/start.sh
                                "
                            """
                        }
                    }
                }
            }
        }
    }
}