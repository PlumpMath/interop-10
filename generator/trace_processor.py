# encoding: utf-8
import json
import os
import time
import random
import subprocess
import threading
import logging
import logging.handlers
import decimal
import re
import sys

from collections import deque
from API_manager import list_content, unlink, make, put_content, get_content, move

log_file_name = "/../interop_experiment_%d.log" % (int(time.time()))
log_file_trace_path = __file__[:__file__.rfind("/")] + log_file_name

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.handlers.RotatingFileHandler(log_file_trace_path, maxBytes=20000000, backupCount=10)
handler.setLevel(logging.INFO)
formatter = logging.Formatter("[%(levelname)s];[%(thread)d];%(asctime)s;%(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
random.seed(18)


def process_log(op_order, tstamp, queued_tstamp, user_out_id, user_out_type, req_t, origin_provider,
                destination_provider, user_in_id, node_id, node_type, size, elapsed, friends_number, has_error="0",
                trace="NULL", exception="NULL", error_msg="NULL", args="NULL", level="TRACE", url="NULL"):
    line = ("[%s];%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s" % (str(level), str(op_order),
                                                                                  str(tstamp), str(queued_tstamp),
                                                                                  str(user_out_id), str(user_out_type),
                                                                                  str(req_t), str(origin_provider),
                                                                                  str(destination_provider),
                                                                                  str(user_in_id), str(node_id),
                                                                                  str(node_type), str(size),
                                                                                  str(elapsed), str(friends_number),
                                                                                  str(has_error), str(trace),
                                                                                  str(exception), str(error_msg),
                                                                                  str(args), str(url)))
    line = re.sub('[^a-zA-Z0-9,/_;:\(\)\[\]\{\}\n\.]', ' ', line)
    logger.info(line)


def process_debug_log(message):
    logger.info("[DEBUG];%s" % (str(message)))


class User(object):
    def __str__(self):
        return str(self.id)

    def __init__(self, user_id, oauth, shared_folder_id, provider, friends_id_factor_dict=None, file0_id=None):
        self.id = user_id
        self.oauth = oauth
        self.shared_folder_id = shared_folder_id
        self.provider = provider
        if friends_id_factor_dict is None:
            self.friends_id_factor_dict = dict()
        else:
            self.friends_id_factor_dict = friends_id_factor_dict
        self.file0_id = file0_id

        self.workspace_folders = list()
        self.workspace_files = list()

        self.node_server_id_dict = dict()
        self.process_thread = None
        TraceProcessor.all_users_dict[self.id] = self
        TraceProcessor.users_list.append(user_id)


class TraceProcessor:
    csv_timestamp = 0
    csv_normalized_timestamp = 1
    csv_user_id = 2
    csv_req_type = 3
    csv_node_id = 4
    csv_node_type = 5
    csv_ext = 6
    csv_size = 7
    csv_user_type = 8
    csv_friend_id = 9
    csv_provider = 10
    csv_queued_tstamp = 11

    all_users_dict = dict()
    processing_threads = dict()
    users_list = list()

    has_error_code = 999

    def __init__(self, p_trace_path, p_generated_trace_path, test=False):
        self.trace_path = p_trace_path
        self.generated_trace_path = p_generated_trace_path
        process_debug_log("Experiment has started")
        process_log("op_order", "tstamp", "queued_tstamp", "user_out_id", "user_out_type", "req_t", "origin_provider",
                    "destination_provider", "user_in_id", "node_id", "node_type", "size", "elapsed", "friends_number",
                    has_error="has_error", trace="trace", exception="exception", error_msg="error_msg", args="args",
                    url="url")
        self.event_dispatcher()

    def event_dispatcher(self):
        self.run_events()

    def run_events(self):
        previous_normalized_timestamp = decimal.Decimal("0.00000000")
        after_last_sleep = decimal.Decimal(time.time())
        zero_decimal = decimal.Decimal("0.00000000")
        decimal_print_precision = decimal.Decimal("0.001")
        with open(self.generated_trace_path, "w") as fw:
            with open(self.trace_path, "r") as fp:
                for i, line in enumerate(fp):
                    print_seq_dots()
                    if i > 0:
                        line = line.rstrip("\n")
                        event = line.split(",")
                        if len(event) == 9:
                            user_id = int(event[TraceProcessor.csv_user_id])

                            if user_id in TraceProcessor.all_users_dict:
                                [do_event, processed_event] = self.preprocessor(event)

                                if do_event:
                                    user_id = processed_event[TraceProcessor.csv_friend_id]

                                    current_normalized_timestamp = decimal.Decimal(event[TraceProcessor.csv_normalized_timestamp])
                                    t_sleep = current_normalized_timestamp - previous_normalized_timestamp
                                    previous_normalized_timestamp = current_normalized_timestamp

                                    # Control sleep time
                                    processor_delay = decimal.Decimal(time.time()) - after_last_sleep
                                    t_sleep = t_sleep - processor_delay
                                    if t_sleep < zero_decimal:
                                        t_sleep = decimal.Decimal("0.00000000")
                                    print_seq_dots(t_sleep.normalize().quantize(decimal_print_precision))
                                    time.sleep(t_sleep)
                                    after_last_sleep = decimal.Decimal(time.time())
                                    new_thread = True
                                    if user_id in self.processing_threads:
                                        t1 = self.processing_threads[user_id]
                                        if t1.isAlive():
                                            t1.add_event(i, event)
                                            new_thread = False

                                    if new_thread:
                                        t1 = ThreadedPetition(user_id, i, event)
                                        t1.setDaemon(True)
                                        t1.start()
                                        self.processing_threads[user_id] = t1

                                    fw.write("%s\n" % (line))
                                else:
                                    process_debug_log("Avoided line [%s]" % (line))
                            else:
                                process_debug_log("Avoided line [%s]" % (line))
                        else:
                            process_debug_log("Avoided line [%s]" % (line))
        self.wait_experiment()

    def preprocessor(self, event_args):
        user_id = int(event_args[TraceProcessor.csv_user_id])

        try:
            user = TraceProcessor.all_users_dict[user_id]
        except KeyError:
            user_id = TraceProcessor.users_list[user_id % len(TraceProcessor.users_list)]
            user = TraceProcessor.all_users_dict[user_id]
            event_args[TraceProcessor.csv_user_id] = str(user_id)

        factors = user.friends_id_factor_dict.values()
        if len(factors) > 0:
            p = decimal.Decimal(str(random.random()))

            factors.sort()
            target = factors[-1]
            multiple = False
            for v in factors:
                if p < v:
                    target = v
                    break
                elif p == v:
                    target = v
                    multiple = True
                    break

            friends_id_list = []
            for u in user.friends_id_factor_dict:
                if user.friends_id_factor_dict[u] == target:
                    friends_id_list.append(u)
                    if not multiple:
                        break

            friend_id = random.sample(friends_id_list, 1)[0]
            friend_id = TraceProcessor.users_list[friend_id % len(TraceProcessor.users_list)]

            try:
                friend = TraceProcessor.all_users_dict[friend_id]
            except KeyError:
                friend = user

            event_args.append(friend.id)  # csv_friend_id
            event_args.append(friend.provider)  # csv_provider

            return [True, event_args]
        else:
            return [False, event_args]

    def wait_experiment(self):
        process_debug_log("Experiment waiting to finalize")
        wait = True
        while wait:
            wait = not wait
            for u in self.processing_threads:
                t = self.processing_threads[u]
                t.join(1)
                print_seq_dots()
                if t.isAlive():
                    wait = True
                    break
        print ("\nExperiment has finished")
        process_debug_log("Experiment has finished")


def print_seq_dots(sleep_time=""):
    sys.stdout.write('.%s' % sleep_time)
    sys.stdout.flush()


class ThreadedPetition(threading.Thread):
    def __init__(self, user, ops_counter, event):
        threading.Thread.__init__(self)
        self.running = False
        self.first_ops_counter = ops_counter
        self.user = user

        self.event_args = deque()
        queued = time.time()
        event.append(queued)
        self.event_args.append([ops_counter, event])

    def add_event(self, ops_counter, event):
        self.first_ops_counter = ops_counter
        queued = time.time()
        event.append(queued)
        self.event_args.append([ops_counter, event])

    def run(self):
        process_debug_log("Thread start %s count %d" % (self.ident, self.first_ops_counter))
        self.running = True
        while len(self.event_args) > 0:
            [ops_counter, event] = self.event_args.popleft()
            # Process op
            switcher = {
                "GetContentResponse": self.process_get,
                "MakeResponse": self.process_make,
                "MoveResponse": self.process_move,
                "PutContentResponse": self.process_put,
                "Unlink": self.process_delete,
            }
            func = switcher.get(event[TraceProcessor.csv_req_type])
            start = time.time()
            has_error = func(event, ops_counter)
            end = time.time()
            elapsed = end - start
            process_log(ops_counter, repr(start), repr(event[TraceProcessor.csv_queued_tstamp]),
                        event[TraceProcessor.csv_user_id], event[TraceProcessor.csv_user_type],
                        event[TraceProcessor.csv_req_type], event[TraceProcessor.csv_provider], "Unknown",
                        event[TraceProcessor.csv_friend_id], event[TraceProcessor.csv_node_id],
                        event[TraceProcessor.csv_node_type], event[TraceProcessor.csv_size], elapsed,
                        len(self.event_args), level="THREAD", has_error=has_error)

        self.running = False

    def process_make(self, event_args, ops_counter):
        process_debug_log("Count %d ProcessMakeResponse node_id %d of user_id %s" % (ops_counter,
                                                                         int(event_args[TraceProcessor.csv_node_id]),
                                                                         int(event_args[TraceProcessor.csv_user_id])))

        user_id = int(event_args[TraceProcessor.csv_user_id])
        node_id = int(event_args[TraceProcessor.csv_node_id])
        is_folder = event_args[TraceProcessor.csv_node_type] == "Directory"
        friend_id = int(event_args[TraceProcessor.csv_friend_id])

        friend = TraceProcessor.all_users_dict[friend_id]
        workspace = friend.shared_folder_id
        oauth = friend.oauth
        is_ss_provider = friend.provider == "SS"
        server_id = None

        url = "NULL"
        start = time.time()
        try:
            start = time.time()
            response = make(oauth, node_id, workspace, is_folder, is_ss_provider)
            end = time.time()
            url = response.url
            if response.status_code == 201:
                json_data = json.loads(response.text)
                server_id = str(json_data["id"])

                elapsed = end - start
                process_log(str(ops_counter), str(repr(start)), str(repr(event_args[TraceProcessor.csv_queued_tstamp])),
                            str(user_id), str(event_args[TraceProcessor.csv_user_type]),
                            str(event_args[TraceProcessor.csv_req_type]),
                            str(TraceProcessor.all_users_dict[user_id].provider),
                            str(TraceProcessor.all_users_dict[friend_id].provider), str(friend_id),
                            str(server_id),
                            str(event_args[TraceProcessor.csv_node_type]), "NULL", str(elapsed),
                            str(len(TraceProcessor.all_users_dict[user_id].friends_id_factor_dict)), url=str(url))
            elif (response.status_code == 400 or response.status_code == 403) and "already" in response.text:
                elapsed = end - start
                start = time.time()
                response = list_content(oauth, parent_id=workspace, is_ss_provider=is_ss_provider)
                end = time.time()
                json_data = response.json()
                content_root = json_data["contents"]
                server_id = None

                for tuppla in content_root:
                    try:
                        name = tuppla["filename"]
                        is_response_folder = tuppla["is_folder"]
                        if name == str(node_id) and is_folder == is_response_folder:
                            server_id = tuppla["id"]
                            break
                    except KeyError:
                        process_debug_log("Failed to extract file_id form get_content at %s" % (response.url))
                elapsed += end - start
                error_msg = "existing_make"
                size = "NULL"
                process_log(str(ops_counter), str(repr(time.time())), str(repr(event_args[TraceProcessor.csv_queued_tstamp])),
                            str(user_id), str(event_args[TraceProcessor.csv_user_type]),
                            str(event_args[TraceProcessor.csv_req_type]),
                            str(TraceProcessor.all_users_dict[user_id].provider),
                            str(TraceProcessor.all_users_dict[friend_id].provider), str(friend_id),
                            str(server_id),
                            str(event_args[TraceProcessor.csv_node_type]), str(size), elapsed,
                            str(len(TraceProcessor.all_users_dict[user_id].friends_id_factor_dict)), url=str(url), error_msg=error_msg)
            else:
                raise ValueError(
                    "Error on response with status_code %d and text {%s}" % (response.status_code, response.text))

            if server_id is not None:
                if node_id not in friend.node_server_id_dict:
                    friend.node_server_id_dict[node_id] = server_id
                if is_folder and server_id not in friend.workspace_folders:
                    friend.workspace_folders.append(server_id)
                elif not is_folder and server_id not in friend.workspace_files:
                    friend.workspace_files.append(server_id)
            return 0
        except Exception as e:
            trace = event_args
            exception = type(e)
            error_msg = e.message
            args = e.args
            size = "NULL"
            level = "ERROR"
            if server_id is None:
                server_id = node_id

            elapsed = time.time() - start
            process_log(str(ops_counter), str(repr(start)), str(repr(event_args[TraceProcessor.csv_queued_tstamp])),
                        str(user_id), str(event_args[TraceProcessor.csv_user_type]),
                        str(event_args[TraceProcessor.csv_req_type]),
                        str(TraceProcessor.all_users_dict[user_id].provider),
                        str(TraceProcessor.all_users_dict[friend_id].provider), str(friend_id), str(server_id),
                        str(event_args[TraceProcessor.csv_node_type]), str(size), str(elapsed),
                        str(len(TraceProcessor.all_users_dict[user_id].friends_id_factor_dict)),
                        str(TraceProcessor.has_error_code), str(trace), str(exception), str(error_msg), str(args),
                        str(level), url=str(url))
            return TraceProcessor.has_error_code

    def process_put(self, event_args, ops_counter):
        process_debug_log("Count %d ProcessPutContentResponse node_id %d of user_id %s" % (ops_counter,
                                                                           int(event_args[TraceProcessor.csv_node_id]),
                                                                           int(event_args[TraceProcessor.csv_user_id])))

        user_id = int(event_args[TraceProcessor.csv_user_id])
        node_id = int(event_args[TraceProcessor.csv_node_id])
        friend_id = int(event_args[TraceProcessor.csv_friend_id])
        size = int(event_args[TraceProcessor.csv_size])

        friend = TraceProcessor.all_users_dict[friend_id]
        oauth = friend.oauth
        is_ss_provider = friend.provider == "SS"

        server_id = None
        local_path = "./%s.file" % (self.ident)
        url = "NULL"
        start = time.time()
        try:
            if node_id not in friend.node_server_id_dict:
                if len(friend.workspace_files) > 0:
                    server_id = random.sample(friend.workspace_files, 1)[0]
                else:
                    server_id = friend.file0_id
            else:
                server_id = friend.node_server_id_dict[node_id]

            if size < 1:
                size = 2
            try:
                with open(local_path, "w"):
                    subprocess.check_call(["fallocate", "-l", str(size), local_path])
            except Exception as e:
                trace = event_args
                exception = type(e)
                error_msg = "fallocate error %s" % (e.message)
                args = e.args
                level = "ERROR"

                elapsed = time.time() - start
                process_log(str(ops_counter), str(repr(start)), str(repr(event_args[TraceProcessor.csv_queued_tstamp])),
                            str(user_id), str(event_args[TraceProcessor.csv_user_type]),
                            str(event_args[TraceProcessor.csv_req_type]),
                            str(TraceProcessor.all_users_dict[user_id].provider),
                            str(TraceProcessor.all_users_dict[friend_id].provider), str(friend_id), str(server_id),
                            str(event_args[TraceProcessor.csv_node_type]), str(size), str(elapsed),
                            str(len(TraceProcessor.all_users_dict[user_id].friends_id_factor_dict)),
                            str(TraceProcessor.has_error_code), str(trace), str(exception), str(error_msg), str(args),
                            str(level), url=str(url))

            start = time.time()
            response = put_content(oauth, server_id, local_path, is_ss_provider)
            end = time.time()
            url = response.url

            if response.status_code == 200 or response.status_code == 201:
                elapsed = end - start
                if friend.provider == "NEC":
                    size = str(size)
                else:
                    json_data = json.loads(response.text)
                    size = str(json_data["size"])

                process_log(str(ops_counter), str(repr(start)), str(repr(event_args[TraceProcessor.csv_queued_tstamp])),
                            str(user_id), str(event_args[TraceProcessor.csv_user_type]),
                            str(event_args[TraceProcessor.csv_req_type]),
                            str(TraceProcessor.all_users_dict[user_id].provider),
                            str(TraceProcessor.all_users_dict[friend_id].provider), str(friend_id),
                            str(server_id),
                            str(event_args[TraceProcessor.csv_node_type]), str(size), str(elapsed),
                            str(len(TraceProcessor.all_users_dict[user_id].friends_id_factor_dict)), url=str(url))
            else:
                raise ValueError(
                    "Error on response with status_code %d and text %s" % (response.status_code, response.text))
            return 0
        except Exception as e:
            trace = event_args
            exception = type(e)
            error_msg = e.message
            args = e.args
            level = "ERROR"
            if server_id is None:
                server_id = node_id

            elapsed = time.time() - start
            process_log(str(ops_counter), str(repr(start)), str(repr(event_args[TraceProcessor.csv_queued_tstamp])),
                        str(user_id), str(event_args[TraceProcessor.csv_user_type]),
                        str(event_args[TraceProcessor.csv_req_type]),
                        str(TraceProcessor.all_users_dict[user_id].provider),
                        str(TraceProcessor.all_users_dict[friend_id].provider), str(friend_id), str(server_id),
                        str(event_args[TraceProcessor.csv_node_type]), str(size), str(elapsed),
                        str(len(TraceProcessor.all_users_dict[user_id].friends_id_factor_dict)),
                        str(TraceProcessor.has_error_code), str(trace), str(exception), str(error_msg), str(args),
                        str(level), url=str(url))
            return TraceProcessor.has_error_code
        finally:
            try:
                os.remove(local_path)
            except:
                process_debug_log("Failed to remove local file %s" % (local_path))

    def process_get(self, event_args, ops_counter):
        process_debug_log("Count %d ProcessGetContentResponse node_id %d of user_id %s" % (ops_counter,
                                                                       int(event_args[TraceProcessor.csv_node_id]),
                                                                       int(event_args[TraceProcessor.csv_user_id])))

        user_id = int(event_args[TraceProcessor.csv_user_id])
        node_id = int(event_args[TraceProcessor.csv_node_id])
        friend_id = int(event_args[TraceProcessor.csv_friend_id])

        friend = TraceProcessor.all_users_dict[friend_id]
        oauth = friend.oauth
        is_ss_provider = friend.provider == "SS"
        server_id = None
        url = "NULL"

        start = time.time()
        try:
            server_id = None
            if node_id in friend.node_server_id_dict:
                server_id = friend.node_server_id_dict[node_id]
            if server_id not in friend.workspace_files:
                if len(friend.workspace_files) > 0:
                    server_id = random.sample(friend.workspace_files, 1)[0]
                else:
                    server_id = friend.file0_id

            start = time.time()
            response = get_content(oauth, server_id, is_ss_provider)
            end = time.time()
            url = response.url

            if response.status_code != 200:
                raise ValueError(
                    "Error on response with status_code %d and text %s" % (response.status_code, response.text))
            elapsed = end - start
            if "content-length" not in response.headers:
                size = len(response.content)
                error_msg = "Get without response.headers content length status_code %d %s" % (
                    response.status_code, response)
            else:
                size = response.headers["content-length"]
                error_msg = "NULL"

            process_log(str(ops_counter), str(repr(start)), str(repr(event_args[TraceProcessor.csv_queued_tstamp])),
                        str(user_id), str(event_args[TraceProcessor.csv_user_type]),
                        str(event_args[TraceProcessor.csv_req_type]),
                        str(TraceProcessor.all_users_dict[user_id].provider),
                        str(TraceProcessor.all_users_dict[friend_id].provider), str(friend_id), str(server_id),
                        str(event_args[TraceProcessor.csv_node_type]), str(size), str(elapsed),
                        str(len(TraceProcessor.all_users_dict[user_id].friends_id_factor_dict)),
                        has_error=str("0"), error_msg=error_msg, url=str(url))
            return 0
        except Exception as e:
            trace = event_args
            exception = type(e)
            error_msg = e.message
            args = e.args
            size = "NULL"
            level = "ERROR"
            if server_id is None:
                server_id = node_id

            elapsed = time.time() - start
            process_log(str(ops_counter), str(repr(start)), str(repr(event_args[TraceProcessor.csv_queued_tstamp])),
                        str(user_id), str(event_args[TraceProcessor.csv_user_type]),
                        str(event_args[TraceProcessor.csv_req_type]),
                        str(TraceProcessor.all_users_dict[user_id].provider),
                        str(TraceProcessor.all_users_dict[friend_id].provider), str(friend_id), str(server_id),
                        str(event_args[TraceProcessor.csv_node_type]), str(size), str(elapsed),
                        str(len(TraceProcessor.all_users_dict[user_id].friends_id_factor_dict)),
                        str(TraceProcessor.has_error_code), str(trace), str(exception), str(error_msg), str(args),
                        str(level), url=str(url))
            return TraceProcessor.has_error_code

    def process_delete(self, event_args, ops_counter):
        process_debug_log("Count %d ProcessUnlink node_id %d of user_id %s" % (ops_counter,
                                                                               int(event_args[
                                                                                       TraceProcessor.csv_node_id]),
                                                                               int(event_args[
                                                                                       TraceProcessor.csv_user_id])))

        user_id = int(event_args[TraceProcessor.csv_user_id])
        node_id = int(event_args[TraceProcessor.csv_node_id])
        is_folder = event_args[TraceProcessor.csv_node_type] == "Directory"
        friend_id = int(event_args[TraceProcessor.csv_friend_id])

        friend = TraceProcessor.all_users_dict[friend_id]
        oauth = friend.oauth
        is_ss_provider = friend.provider == "SS"

        fake_delete = False
        server_id = None
        url = "NULL"

        start = time.time()
        try:
            server_id = None
            if node_id in friend.node_server_id_dict:
                server_id = friend.node_server_id_dict[node_id]

            if is_folder:
                if server_id not in friend.workspace_folders:
                    if len(friend.workspace_folders) > 0:
                        server_id = random.sample(friend.workspace_folders, 1)[0]
                    else:
                        server_id = friend.shared_folder_id
                        fake_delete = True
            else:
                if server_id not in friend.workspace_files:
                    if len(friend.workspace_files) > 0:
                        server_id = random.sample(friend.workspace_files, 1)[0]
                    else:
                        server_id = friend.file0_id
                        fake_delete = True

            if not fake_delete:
                start = time.time()
                response = unlink(oauth, server_id, is_folder, is_ss_provider)
                end = time.time()
                url = response.url

                if response.status_code == 200:
                    if is_folder:
                        friend.workspace_folders.remove(server_id)
                    else:
                        friend.workspace_files.remove(server_id)
                    for k in friend.node_server_id_dict:
                        if friend.node_server_id_dict[k] == server_id:
                            friend.node_server_id_dict.pop(k)
                            break

                    elapsed = end - start

                    process_log(str(ops_counter), str(repr(start)), str(repr(event_args[TraceProcessor.csv_queued_tstamp])),
                                str(user_id), str(event_args[TraceProcessor.csv_user_type]),
                                str(event_args[TraceProcessor.csv_req_type]),
                                str(TraceProcessor.all_users_dict[user_id].provider),
                                str(TraceProcessor.all_users_dict[friend_id].provider), str(friend_id),
                                str(server_id),
                                str(event_args[TraceProcessor.csv_node_type]), str(event_args[TraceProcessor.csv_size]),
                                str(elapsed),
                                str(len(TraceProcessor.all_users_dict[user_id].friends_id_factor_dict)), url=str(url))
                else:
                    raise ValueError(
                        "Error on response with status_code %d and text %s" % (response.status_code, response.text))
            else:
                elapsed = "0.725152481329475"
                has_error = "0"
                error_msg = "fake_delete"

                process_log(str(ops_counter), str(repr(time.time())), str(repr(event_args[TraceProcessor.csv_queued_tstamp])),
                            str(user_id), str(event_args[TraceProcessor.csv_user_type]),
                            str(event_args[TraceProcessor.csv_req_type]),
                            str(TraceProcessor.all_users_dict[user_id].provider),
                            str(TraceProcessor.all_users_dict[friend_id].provider),
                            str(friend_id), str(server_id), str(event_args[TraceProcessor.csv_node_type]),
                            str(event_args[TraceProcessor.csv_size]), str(elapsed),
                            str(len(TraceProcessor.all_users_dict[user_id].friends_id_factor_dict)),
                            has_error=str(has_error), error_msg=str(error_msg), url=str(url))
            return 0
        except Exception as e:
            trace = event_args
            exception = type(e)
            error_msg = e.message
            args = e.args
            size = "NULL"
            level = "ERROR"
            if server_id is None:
                server_id = node_id

            elapsed = time.time() - start
            process_log(str(ops_counter), str(repr(start)), str(repr(event_args[TraceProcessor.csv_queued_tstamp])),
                        str(user_id), str(event_args[TraceProcessor.csv_user_type]),
                        str(event_args[TraceProcessor.csv_req_type]),
                        str(TraceProcessor.all_users_dict[user_id].provider),
                        str(TraceProcessor.all_users_dict[friend_id].provider), str(friend_id), str(server_id),
                        str(event_args[TraceProcessor.csv_node_type]), str(size), str(elapsed),
                        str(len(TraceProcessor.all_users_dict[user_id].friends_id_factor_dict)),
                        str(TraceProcessor.has_error_code), str(trace), str(exception), str(error_msg), str(args),
                        str(level), url=str(url))
            return TraceProcessor.has_error_code

    def process_move(self, event_args, ops_counter):
        process_debug_log("Count %d Process MoveResponse node_id %d of user_id %s" % (ops_counter,
                                                                          int(event_args[TraceProcessor.csv_node_id]),
                                                                          int(event_args[TraceProcessor.csv_user_id])))
        user_id = int(event_args[TraceProcessor.csv_user_id])
        node_id = int(event_args[TraceProcessor.csv_node_id])
        is_folder = event_args[TraceProcessor.csv_node_type] == "Directory"
        friend_id = int(event_args[TraceProcessor.csv_friend_id])

        user = TraceProcessor.all_users_dict[user_id]
        friend = TraceProcessor.all_users_dict[friend_id]
        oauth = friend.oauth
        is_ss_provider = friend.provider == "SS"
        destination_folder = friend.shared_folder_id
        server_id = None
        url = "NULL"

        start = time.time()
        try:
            server_id = None
            if node_id in friend.node_server_id_dict:
                server_id = friend.node_server_id_dict[node_id]

            if is_folder:
                if server_id not in user.workspace_folders:
                    if len(user.workspace_folders) > 0:
                        server_id = random.sample(user.workspace_folders, 1)[0]
                    else:
                        raise ValueError("Error friend %d workspace does not have any folder to move" % (friend_id))
                else:
                    raise ValueError("Error friend %d workspace does not have any folder" % (friend_id))
            else:
                if server_id not in user.workspace_files:
                    if len(user.workspace_files) > 0:
                        server_id = random.sample(user.workspace_files, 1)[0]
                    else:
                        raise ValueError("Error friend %d workspace does not have any file to move" % (friend_id))
                else:
                    raise ValueError("Error friend %d workspace does not have any file" % (friend_id))

            start = time.time()
            response = move(oauth, server_id, destination_folder, is_folder, is_ss_provider)
            end = time.time()
            url = response.url

            if response.status_code != 200:
                raise ValueError(
                    "Error on response with status_code %d and text %s" % (response.status_code, response.text))
            elapsed = end - start

            if is_folder:
                user.workspace_folders.remove(server_id)
                friend.workspace_folders.append(server_id)
            else:
                user.workspace_files.remove(server_id)
                friend.workspace_files.append(server_id)

            process_log(str(ops_counter), str(repr(start)), str(repr(event_args[TraceProcessor.csv_queued_tstamp])),
                        str(user_id), str(event_args[TraceProcessor.csv_user_type]),
                        str(event_args[TraceProcessor.csv_req_type]),
                        str(TraceProcessor.all_users_dict[user_id].provider),
                        str(TraceProcessor.all_users_dict[friend_id].provider), str(friend_id), str(server_id),
                        str(event_args[TraceProcessor.csv_node_type]), str(event_args[TraceProcessor.csv_size]),
                        str(elapsed),
                        str(len(TraceProcessor.all_users_dict[user_id].friends_id_factor_dict)), url=str(url))
            return 0
        except Exception as e:
            trace = event_args
            exception = type(e)
            error_msg = e.message
            args = e.args
            size = "NULL"
            level = "ERROR"
            if server_id is None:
                server_id = node_id

            elapsed = time.time() - start
            process_log(str(ops_counter), str(repr(start)), str(repr(event_args[TraceProcessor.csv_queued_tstamp])),
                        str(user_id), str(event_args[TraceProcessor.csv_user_type]),
                        str(event_args[TraceProcessor.csv_req_type]),
                        str(TraceProcessor.all_users_dict[user_id].provider),
                        str(TraceProcessor.all_users_dict[friend_id].provider), str(friend_id), str(server_id),
                        str(event_args[TraceProcessor.csv_node_type]), str(size), str(elapsed),
                        str(len(TraceProcessor.all_users_dict[user_id].friends_id_factor_dict)),
                        str(TraceProcessor.has_error_code), str(trace), str(exception), str(error_msg), str(args),
                        str(level), url=str(url))
            return TraceProcessor.has_error_code

if __name__ == "__main__":
    print "Error: This class must be instantiated"
