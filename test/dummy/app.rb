require 'sinatra'
require 'redis'

get '/' do
  redis_client = Redis.new(host: ENV['REDIS_HOST'])
  has_ec2_access = system("aws ec2 describe-instances --region us-west-2 --max-items 1") ? "True" : "False"
  "This is dummy app. Label: #{ENV['LABEL']}. Redis PING: #{redis_client.ping}. AWS EC2 READ ACCESS: #{has_ec2_access}"
end

get '/elb-check' do
  "This is dummy app. Label: #{ENV['LABEL']}"
end