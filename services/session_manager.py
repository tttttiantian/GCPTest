"""
会话管理器 - 负责创建、管理、清理用户会话
"""
import uuid
import os
import shutil
from datetime import datetime
from typing import Optional
from threading import Lock


class SessionManager:
    """会话管理器 - 负责创建、管理、清理用户会话"""

    def __init__(self, base_upload_folder: str):
        self.base_folder = base_upload_folder
        self.sessions = {}  # 内存中保存会话信息
        self.lock = Lock()
        self.session_ttl = 3600  # 会话有效期1小时
        self.session_counter = 0  # 会话计数器

    def create_session(self) -> dict:
        """
        创建新会话 - 使用session_id前8位作为文件夹名（确保多worker环境下唯一性）

        Returns:
            {
                'session_id': str,
                'session_folder': str,
                'folder_name': str,  # 文件夹名
                'created_at': datetime
            }
        """
        with self.lock:
            # session_id使用UUID（全局唯一）
            session_id = str(uuid.uuid4())

            # 使用session_id前8位作为文件夹名，确保跨worker唯一性
            folder_name = f"session_{session_id[:8]}"
            session_folder = os.path.join(self.base_folder, folder_name)

            os.makedirs(session_folder, exist_ok=True)

            # 创建.session_id文件，用于跨worker进程查找
            session_id_file = os.path.join(session_folder, '.session_id')
            with open(session_id_file, 'w') as f:
                f.write(session_id)

            session_info = {
                'session_id': session_id,
                'session_folder': session_folder,
                'folder_name': folder_name,
                'created_at': datetime.now()
            }

            self.sessions[session_id] = session_info
            print(f"[SESSION] Created new session: {session_id} -> {folder_name}")
            return session_info

    def get_session(self, session_id: str) -> Optional[dict]:
        """获取会话信息"""
        with self.lock:
            session = self.sessions.get(session_id)

            # 如果内存中没有（可能是多worker环境），尝试从文件系统恢复
            if not session:
                session = self._recover_session_from_filesystem(session_id)
                if session:
                    self.sessions[session_id] = session

            return session

    def _recover_session_from_filesystem(self, session_id: str) -> Optional[dict]:
        """
        从文件系统恢复会话信息（用于多worker环境）

        遍历uploads目录下的所有session_*文件夹，检查.session_id文件
        """
        try:
            if not os.path.exists(self.base_folder):
                print(f"[SESSION] Base folder not found: {self.base_folder}")
                return None

            print(f"[SESSION] Attempting to recover session {session_id[:8]}... from filesystem")
            print(f"[SESSION] Scanning directory: {self.base_folder}")

            # 遍历所有session文件夹
            for folder_name in os.listdir(self.base_folder):
                folder_path = os.path.join(self.base_folder, folder_name)

                # 检查是否是目录且符合session_*模式
                if not os.path.isdir(folder_path) or not folder_name.startswith('session_'):
                    continue

                # 检查.session_id文件
                session_id_file = os.path.join(folder_path, '.session_id')
                if os.path.exists(session_id_file):
                    with open(session_id_file, 'r') as f:
                        stored_session_id = f.read().strip()

                    print(f"[SESSION] Found session file in {folder_name}: {stored_session_id[:8]}...")

                    if stored_session_id == session_id:
                        # 恢复session信息
                        session_info = {
                            'session_id': session_id,
                            'session_folder': folder_path,
                            'folder_name': folder_name,
                            'created_at': datetime.fromtimestamp(os.path.getctime(folder_path))
                        }
                        print(f"[SESSION] ✓ Successfully recovered session from {folder_name}")
                        return session_info

            print(f"[SESSION] ✗ Session {session_id[:8]}... not found in filesystem")
            return None

        except Exception as e:
            print(f"[SESSION] 恢复会话失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_session_dir(self, session_id: str) -> Optional[str]:
        """
        获取会话的工作目录

        Args:
            session_id: 会话ID

        Returns:
            会话目录路径，如果会话不存在返回None
        """
        with self.lock:
            session = self.sessions.get(session_id)
            if session:
                return session.get('session_folder')
            return None

    def update_test_file(self, session_id: str, test_code: str) -> bool:
        """
        更新会话中的测试文件内容（可选：保存历史版本）

        Args:
            session_id: 会话ID
            test_code: 新的测试代码

        Returns:
            是否更新成功
        """
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return False

            # 可选：保存历史版本
            if 'test_history' not in session:
                session['test_history'] = []

            session['test_history'].append({
                'timestamp': datetime.now().isoformat(),
                'code': test_code
            })

            # 限制历史记录数量（避免内存溢出）
            if len(session['test_history']) > 10:
                session['test_history'] = session['test_history'][-10:]

            return True

    def cleanup_session(self, session_id: str):
        """清理会话文件和缓存"""
        with self.lock:
            session = self.sessions.get(session_id)
            if session and os.path.exists(session['session_folder']):
                try:
                    shutil.rmtree(session['session_folder'])
                except Exception as e:
                    print(f"清理会话目录失败: {e}")

            if session_id in self.sessions:
                del self.sessions[session_id]

    def cleanup_old_sessions(self, max_age_seconds: int = 3600):
        """清理超过1小时的旧会话"""
        with self.lock:
            now = datetime.now()
            to_delete = []

            for sid, info in self.sessions.items():
                age = (now - info['created_at']).total_seconds()
                if age > max_age_seconds:
                    to_delete.append(sid)

            for sid in to_delete:
                self.cleanup_session(sid)
